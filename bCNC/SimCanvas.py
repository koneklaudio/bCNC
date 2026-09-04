import math
import time
import sys
from glm import pi
from numpy import deg2rad
from tkinter_gl import GLCanvas

import OpenGL

if sys.platform == 'linux':
    # PyOpenGL is broken with wayland:
    OpenGL.setPlatform('x11')

from OpenGL.GL import *
from ctypes import c_void_p
from pyglm.glm import mat4x4, mat3x3, ortho, identity, value_ptr, inverse, translate, rotate, vec2, vec3, vec4, inverse, normalize, lookAt, dot, cross, distance, length2, sin, cos
import os

from tkinter import (
    TclError,
    FALSE,
    N,
    S,
    W,
    E,
    NS,
    EW,
    NSEW,
    CENTER,
    NONE,
    BOTH,
    LEFT,
    RIGHT,
    RAISED,
    HORIZONTAL,
    VERTICAL,
    ALL,
    DISABLED,
    LAST,
    SCROLL,
    UNITS,
    StringVar,
    IntVar,
    BooleanVar,
    DoubleVar,
    Button,
    Canvas,
    Checkbutton,
    Frame,
    Label,
    Radiobutton,
    Scrollbar,
    OptionMenu,
    Toplevel,
    LabelFrame,
    messagebox
)
import tkinter

import bmath
import Camera
import tkExtra
import Utils
from CNC import CNC, Probe
import CNCCanvas

# Probe mapping we need PIL and numpy
try:
    from PIL import Image, ImageTk, ImageFont, ImageDraw
    import numpy

    # Resampling image based on PIL library and converting to RGB.
    # options possible: NEAREST, BILINEAR, BICUBIC, ANTIALIAS
    RESAMPLE = Image.NEAREST  # resize type
except Exception:
    from tkinter import Image
    numpy = None
    RESAMPLE = None

try:
    import OpenGL
    if sys.platform == 'linux':
        # PyOpenGL is broken with wayland:
        OpenGL.setPlatform('x11')
    from OpenGL import GL
except ImportError:
    raise ImportError(
        """
        This example requires PyOpenGL.

        You can install it with "pip install PyOpenGL".
        """)

ZOOM = 1.25

ACTION_PAN = 10
ACTION_ZOOM = 12
ACTION_ROTATE = 21

DEF_CURSOR = ""
MOUSE_CURSOR = {
    ACTION_PAN: "fleur",
    ACTION_ROTATE: "exchange",
    ACTION_ZOOM: "circle"
}

HEIGHTMAP_RES = 10000
MESH_RES = 1000
STOCK_MIN_X = 0
STOCK_MAX_X = 100
STOCK_MIN_Y = 0
STOCK_MAX_Y = 100
STOCK_MIN_Z = 0.
STOCK_MAX_Z = 20.
MILL_TYPES = {"Flat": 0, "Ball": 1}
MILL_DIAMETER = 6.

def mouseCursor(action):
    return MOUSE_CURSOR.get(action, DEF_CURSOR)

# =============================================================================
# Simulation canvas
# =============================================================================
class SimCanvas(GLCanvas):
    profile = 'legacy'
    
    def __init__(self, master, app, *kw, **kwargs):
        super().__init__(master)

        self.app = app
        self.cncCanvas = app.canvas

        self.windowing_system = self.app.call('tk', 'windowingsystem')

        # Canvas binding
        self.bind("<Button-1>", self.click)
        self.bind("<Configure>", self.configureEvent)
        self.bind("<Button-2>", self.midClick)
        self.bind("<B2-Motion>", self.pan)
        self.bind("<ButtonRelease-2>", self.midRelease)
        self.bind("<Button-3>", self.rightClick)
        self.bind("<B3-Motion>", self.rotate)
        self.bind("<ButtonRelease-3>", self.rightRelease)
        self.bind("<Button-4>", self.mouseZoomIn)
        self.bind("<Button-5>", self.mouseZoomOut)
        self.bind("<MouseWheel>", self.wheel)
        self.bind("<Key>", self.handleKey)

        # Milling vars
        self.millType = StringVar()
        self.millDiameter = DoubleVar()

        # OPENGL vars
        self.MVMatrix = identity(mat4x4) # Model View Matrix
        self.PMatrix = ortho(-100, 100, -100, 100, -10000, 10000) # Projection matrix. Updated on resize

        self._drawRequested = False
        self._x = self._y = 0
        self._xp = self._yp = 0
        self._mouseAction = None
        self.__tzoom = 1.0  # delayed zoom (temporary)
        self.zoom = 1.

        self._gl_initialized = False

        self._make_current()
        self.initGL()

        self._gl_initialized = True
    
    def click(self, event):
        self.focus_set()

    def handleKey(self, event):
        if event.char == "f":
            self.fit2Screen()
    
    def rgb8(self, colorName):
        return (numpy.array(self.winfo_rgb(colorName)) * 255. / 65535.).astype(int)
    
    def configureEvent(self, event):
        self.draw()
    
    def midClick(self, event):
        self.focus_set()
        self._x = self._xp = event.x
        self._y = self._yp = event.y
    
    def rightClick(self, event):
        self.focus_set()
        self._x = event.x
        self._y = event.y
    
    def rightRelease(self, event):
        self.configure(cursor=mouseCursor(DEF_CURSOR))

    def pan(self, event):
        if self._mouseAction != ACTION_PAN:
            self.configure(cursor=mouseCursor(ACTION_PAN))
            self._mouseAction = ACTION_PAN
            
        self.pan_delta(event.x - self._x, event.y - self._y)
        
        self._x = event.x
        self._y = event.y
    
    def pan_delta(self, deltaX, deltaY):
        """
        Pan a number of pixels in X and/or Y
        """
        width = self.winfo_width()
        height = self.winfo_height()
        
        MVPinv = inverse(self.PMatrix * self.MVMatrix)
        
        pointFrom = MVPinv * vec4(-1, 1, 0, 1) # Screen (0, 0)
        pointTo = MVPinv * vec4(2 * (deltaX - width / 2.0) / width, 2 * (height / 2.0 - deltaY) / height, 0, 1) # Screen (deltaX, deltaY)

        self.MVMatrix = translate(self.MVMatrix, vec3((pointTo - pointFrom).x, (pointTo - pointFrom).y, (pointTo - pointFrom).z)) # type: ignore
        
        self.queueDraw()
    
    # ----------------------------------------------------------------------
    def mouseZoomIn(self, event):
        self.zoomCanvas(event.x, event.y, ZOOM)

    # ----------------------------------------------------------------------
    def mouseZoomOut(self, event):
        self.zoomCanvas(event.x, event.y, 1.0 / ZOOM)

    # ----------------------------------------------------------------------
    # Delay zooming to cascade multiple zoom actions
    # ----------------------------------------------------------------------
    def zoomCanvas(self, x, y, zoom):
        self._tx = x
        self._ty = y
        self.__tzoom *= zoom
        self.after_idle(self._zoomCanvas)

    # ----------------------------------------------------------------------
    # Zoom on screen position x,y by a factor zoom
    # ----------------------------------------------------------------------
    def _zoomCanvas(self, event=None):  # x, y, zoom):
        x = self._tx
        y = self._ty
        zoom = self.__tzoom

        self.__tzoom = 1.0

        width = self.winfo_width()
        height = self.winfo_height()     
        
        MVP = self.PMatrix * self.MVMatrix          
        
        # We zoom around the (x, y) screen location 
        zoomOrigin3d = self.canvas2World(vec2(x, y))
        
        screenCenter3d = (inverse(MVP) * vec4(0, 0, 0, 1)).xyz
        
        # Vector from zoom origin to projected center
        vZoomOriginToCenter = screenCenter3d - zoomOrigin3d
        
        # Translate the model, so that the origin keeps fixed when zooming
        self.MVMatrix = translate(self.MVMatrix, vZoomOriginToCenter * (1- 1/zoom))
        

        # Zoom around the mouse location
        
        self.zoom *= zoom
        
        self.PMatrix = ortho(-width / 2.0 / self.zoom, 
                             width / 2.0 / self.zoom, 
                             -height / 2.0 / self.zoom,
                             height / 2.0 / self.zoom, 
                             -10000,
                             10000)

        self.queueDraw()

    # ----------------------------------------------------------------------
    def wheel(self, event):
        # In windows, each wheel step counts 120
        if self.windowing_system == "win32":
            wheel_step = 120
        else:
            wheel_step = 1

        self.zoomCanvas(event.x, event.y, pow(ZOOM, (event.delta // wheel_step)))
    
    def rotate(self, event):
        if (self._x == event.x and self._y == event.y):
            return
        
        self.configure(cursor=mouseCursor(ACTION_ROTATE))

        RotAxis = normalize(vec4(event.y - self._y, event.x - self._x, 0, 0))
        
        RotAxis = inverse(self.MVMatrix) * RotAxis

        # Rotate about the Center of the screen
        rotationCenter = self.canvas2World(vec2(self.winfo_width() / 2., self.winfo_height() / 2.))

        self.MVMatrix = translate(self.MVMatrix, rotationCenter)

        self.MVMatrix = rotate(self.MVMatrix,
            0.01 * math.sqrt(pow(event.y - self._y, 2) + math.pow(event.x - self._x, 2)),
            vec3(RotAxis.x, RotAxis.y, RotAxis.z)) # type: ignore

        self.MVMatrix = translate(self.MVMatrix, -rotationCenter)
        
        self._x = event.x
        self._y = event.y
        
        self.queueDraw()
    
    def midRelease(self, event):
        # If there was no pan (just mid-click), and the user clicked on a path, 
        # change the rotation center to the point of the stock upper surface (unmilled stock) where the user clicked
        if self._mouseAction != ACTION_PAN and self._mouseAction != ACTION_ZOOM:
            #newRotationCenter, pointType = self.snapPoint(vec2(event.x, event.y))
            newRotationCenter = None

            pClicked = self.canvas2WorldPlane(self.canvas2Unit(vec2(event.x, event.y)), vec3(0, 0, 1), vec3(0, 0, STOCK_MAX_Z), 1)

            if pClicked is not None:
                if pClicked.x >= STOCK_MIN_X and pClicked.x <= STOCK_MAX_X and pClicked.y >= STOCK_MIN_Y and pClicked.y <= STOCK_MAX_Y:
                    newRotationCenter = pClicked

            # TODO: Implement change of rotation center
            if newRotationCenter is not None:
                RS = mat3x3(self.MVMatrix)
                new_translation = -RS * newRotationCenter
                self.MVMatrix[3] = vec4(new_translation, 1)

                self.queueDraw()

        self._mouseAction = None
        self.configure(cursor=mouseCursor(DEF_CURSOR))
    
    def canvas2Unit(self, coords : vec2) -> vec2:
        """
        Map screen pixel coordinates to opengl screen coords [-1.0 -> 1.0]
        In OpenGL, y goes positive upwards
        """
        width = self.winfo_width()
        height = self.winfo_height()
        
        return vec2(
            coords.x / (width / 2.0) - 1,
            1 - coords.y / (height / 2.0)
        )
    
    def canvas2World(self, coords : vec2) -> vec3:
        coordsUnit = self.canvas2Unit(coords)
        
        MVPinv = inverse(self.PMatrix * self.MVMatrix)
        
        return (MVPinv * vec4(coordsUnit, 0, 1)).xyz

    def queueDraw(self):
        if self._drawRequested:
            return
        
        self._drawRequested = True
        
        self.after('idle', self.draw)
    
    def draw(self):
        if not self._gl_initialized:
            return
        
        self._make_current()
        width, height = self.winfo_width(), self.winfo_height()
        
        # Check readiness of the buffer
        if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            self._drawRequested = False
            self.queueDraw()
            return

        glViewport(0, 0, width, height)
        
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT) # type: ignore
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glEnable(GL_BLEND)
        glEnable(GL_LINE_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)

        # Draw background
        self.drawBackground()
        # Ensure that the next items are drawn on top of this
        glClear(GL_DEPTH_BUFFER_BIT)

        # Draw stock material
        self.drawStockTop()
        self.drawStockBottom()
        self.drawStockSide(1)
        self.drawStockSide(2)
        self.drawStockSide(3)
        self.drawStockSide(4)

        glUseProgram(0)
        
        self.swap_buffers()
        
        self._drawRequested = False

    
    def createProgram(self, vertexShaderCode, fragmentShaderCode):
        # Compile Vertex Shader
        vertex_shader = glCreateShader(GL_VERTEX_SHADER)
        glShaderSource(vertex_shader, vertexShaderCode)
        glCompileShader(vertex_shader)
        if not glGetShaderiv(vertex_shader, GL_COMPILE_STATUS):
            raise RuntimeError(glGetShaderInfoLog(vertex_shader))

        # Compile Fragment Shader
        fragment_shader = glCreateShader(GL_FRAGMENT_SHADER)
        glShaderSource(fragment_shader, fragmentShaderCode)
        glCompileShader(fragment_shader)
        if not glGetShaderiv(fragment_shader, GL_COMPILE_STATUS):
            raise RuntimeError(glGetShaderInfoLog(fragment_shader))

        # Link Shaders into a Program
        shader_program = glCreateProgram()
        glAttachShader(shader_program, vertex_shader)
        glAttachShader(shader_program, fragment_shader)
        glLinkProgram(shader_program)
        if not glGetProgramiv(shader_program, GL_LINK_STATUS):
            raise RuntimeError(glGetProgramInfoLog(shader_program))

        # Clean up shaders (no longer needed after linking)
        glDeleteShader(vertex_shader)
        glDeleteShader(fragment_shader)
        
        return shader_program

    def initGL(self):
        self._make_current()
        # Create textures (height map) and framebuffers for milling simulation.
        # The MillFS fragment shader reads the mapheight from FBO 0, writes changes to FBO 1, and then that area is copied back to FBO 0.
        self.textures = glGenTextures(2)
        self.fbos = glGenFramebuffers(2)

        for i in range(2):
            glBindTexture(
                GL_TEXTURE_2D,
                self.textures[i]
            )

            glTexParameteri(
                GL_TEXTURE_2D,
                GL_TEXTURE_MIN_FILTER,
                GL_LINEAR
            )

            glTexParameteri(
                GL_TEXTURE_2D,
                GL_TEXTURE_MAG_FILTER,
                GL_LINEAR
            )

            glTexParameteri(
                GL_TEXTURE_2D,
                GL_TEXTURE_WRAP_S,
                GL_CLAMP_TO_EDGE
            )

            glTexParameteri(
                GL_TEXTURE_2D,
                GL_TEXTURE_WRAP_T,
                GL_CLAMP_TO_EDGE
            )

            # One-channel 32-bit floating point height.
            glTexImage2D(
                GL_TEXTURE_2D,
                0,
                GL_R32F,
                HEIGHTMAP_RES,
                HEIGHTMAP_RES,
                0,
                GL_RED,
                GL_FLOAT,
                None
            )

            glBindFramebuffer(
                GL_FRAMEBUFFER,
                self.fbos[i]
            )

            glFramebufferTexture2D(
                GL_FRAMEBUFFER,
                GL_COLOR_ATTACHMENT0,
                GL_TEXTURE_2D,
                self.textures[i],
                0
            )

            glDrawBuffers([GL_COLOR_ATTACHMENT0])

            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)

            if status != GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError(
                    "Height FBO {} incomplete: {}".format(
                        i,
                        hex(status)
                    )
                )

        glBindTexture(GL_TEXTURE_2D, 0)

        glBindFramebuffer(GL_FRAMEBUFFER, 0)

        self.reset()

        # Create all the OpenGL shader programs

        # ----- BACKGROUND PROGRAM ------
        # Vertex Shader code
        with open(CNCCanvas.openglFolder + "BackgroundVS.shd", "r") as file:
            BackgroundVSCode = file.read()

        # Fragment Shader code
        with open(CNCCanvas.openglFolder + "BackgroundFS.shd", "r") as file:
            BackgroundFSCode = file.read()

        self.backgroundProgram = self.createProgram(BackgroundVSCode, BackgroundFSCode)

        # Create a Vertex Buffer Object (VBO)
        self.backgroundVBO = glGenBuffers(1)

        # Since the background is fixed, we set the buffer data here   
        glBindBuffer(GL_ARRAY_BUFFER, self.backgroundVBO)
        
        vertices = numpy.array([1, 2, 3, 1, 3, 4], dtype=numpy.float32)
        
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        # ----- MILLING PROGRAM ------
        # Vertex Shader code
        with open(CNCCanvas.openglFolder + "MillVS.shd", "r") as file:
            MillVSCode = file.read()

        # Fragment Shader code
        with open(CNCCanvas.openglFolder + "MillFS.shd", "r") as file:
            MillFSCode = file.read()

        self.millProgram = self.createProgram(MillVSCode, MillFSCode)

        # Create a Vertex Buffer Object (VBO)
        self.millVBO = glGenBuffers(1)

        # We create the fixed fullscreen triangle for the milling texture rendering
        vertices = numpy.array([-1, -1, 3, -1, -1, 3], dtype=numpy.float32)
        glBindBuffer(GL_ARRAY_BUFFER, self.millVBO)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        # ----- STOCK TOP PROGRAM ------
        # Vertex Shader code
        with open(CNCCanvas.openglFolder + "StockMaterialVS.shd", "r") as file:
            StockMaterialVSCode = file.read()

        # Fragment Shader code
        with open(CNCCanvas.openglFolder + "StockMaterialFS.shd", "r") as file:
            StockMaterialFSCode = file.read()

        self.stockTopProgram = self.createProgram(StockMaterialVSCode, StockMaterialFSCode)

        # Create a Vertex Buffer Object (VBO)
        self.stockTopVBO = glGenBuffers(1)

        # Create an Element Buffer Object (EBO)
        self.stockTopEBO = glGenBuffers(1)

        # Create the stock material vertices and indices
        self.updateStockMaterialBuffers(MESH_RES, MESH_RES)

        # ----- STOCK BOTTOM PROGRAM ------
        # Vertex Shader code
        with open(CNCCanvas.openglFolder + "StockBottomVS.shd", "r") as file:
            StockBottomVSCode = file.read()

        # Fragment Shader code
        with open(CNCCanvas.openglFolder + "StockBottomFS.shd", "r") as file:
            StockBottomFSCode = file.read()

        self.stockBottomProgram = self.createProgram(StockBottomVSCode, StockBottomFSCode)

        # Create a Vertex Buffer Object (VBO)
        self.stockBottomVBO = glGenBuffers(1)

        # Create the stock bottom vertex indices
        indices = numpy.array([1, 2, 3, 1, 3, 4], dtype=numpy.float32)
              
        glBindBuffer(GL_ARRAY_BUFFER, self.stockBottomVBO)     
        glBufferData(GL_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        # ----- STOCK SIDE PROGRAM ------
        # Vertex Shader code
        with open(CNCCanvas.openglFolder + "StockSideVS.shd", "r") as file:
            StockSideVSCode = file.read()

        # Fragment Shader code
        with open(CNCCanvas.openglFolder + "StockSideFS.shd", "r") as file:
            StockSideFSCode = file.read()

        self.stockSideProgram = self.createProgram(StockSideVSCode, StockSideFSCode)

        # Create a Vertex Buffer Object (VBO)
        self.stockSideVBO = glGenBuffers(1)

        # Create the stock side vertex indices
        indices = numpy.array([1, 2, 3, 1, 3, 4], dtype=numpy.float32)
              
        glBindBuffer(GL_ARRAY_BUFFER, self.stockSideVBO)     
        glBufferData(GL_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def _make_current(self):
        #self.update_idletasks()
        if self.app.openglContext == self:
            return
        
        self.app.openglContext = self
        self.make_current()

        if glGetString(GL_VERSION) is None:
            raise RuntimeError(
                "SimCanvas: OpenGL context not available"
            )
    
    def reset(self):
        self._make_current()

        glDisable(GL_SCISSOR_TEST)
        
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.fbos[0])

        glViewport(0, 0, HEIGHTMAP_RES, HEIGHTMAP_RES)

        #glClearBufferfv(GL_COLOR, 0, [STOCK_MAX_Z, 0.0, 0.0, 0.0])
        glClear(GL_COLOR_BUFFER_BIT)
        glClearColor(STOCK_MAX_Z, 0.0, 0.0, 0.0)

        glBindFramebuffer(GL_FRAMEBUFFER, 0)

        self.queueDraw()

    def drawBackground(self):
        self._make_current()

        glUseProgram(self.backgroundProgram)
        glBindBuffer(GL_ARRAY_BUFFER, self.backgroundVBO)
        PARAMETERS_PER_VERTEX = 1
        glVertexAttribPointer(glGetAttribLocation(self.backgroundProgram, "index"), 1, GL_FLOAT, GL_FALSE, PARAMETERS_PER_VERTEX*4, c_void_p(0*4))
        glEnableVertexAttribArray(glGetAttribLocation(self.backgroundProgram, "index"))

        canvas_color_rgb_up = vec3(self.rgb8(CNCCanvas.CANVAS_COLOR_UP))
        canvas_color_rgb_up_loc = glGetUniformLocation(program=self.backgroundProgram, name="canvas_color_rgb_up")
        glUniform3fv(canvas_color_rgb_up_loc, 1, value_ptr(canvas_color_rgb_up))

        canvas_color_rgb_down = vec3(self.rgb8(CNCCanvas.CANVAS_COLOR_DOWN))
        canvas_color_rgb_down_loc = glGetUniformLocation(program=self.backgroundProgram, name="canvas_color_rgb_down")
        glUniform3fv(canvas_color_rgb_down_loc, 1, value_ptr(canvas_color_rgb_down))

        glDrawArrays(GL_TRIANGLES, 0, 6)

        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def drawStockTop(self):
        self._make_current()

        glUseProgram(self.stockTopProgram)
        glBindBuffer(GL_ARRAY_BUFFER, self.stockTopVBO)
        PARAMETERS_PER_VERTEX = 2
        glVertexAttribPointer(glGetAttribLocation(self.stockTopProgram, "uv"), 2, GL_FLOAT, GL_FALSE, PARAMETERS_PER_VERTEX*4, c_void_p(0*4))
        glEnableVertexAttribArray(glGetAttribLocation(self.stockTopProgram, "uv"))

        MVP = self.PMatrix * self.MVMatrix
        mv_loc = glGetUniformLocation(program=self.stockTopProgram, name="MVP")
        glUniformMatrix4fv(mv_loc, 1, False, value_ptr(MVP))

        glActiveTexture(GL_TEXTURE0)

        glBindTexture(GL_TEXTURE_2D, self.textures[0])

        glUniform1i(glGetUniformLocation(self.stockTopProgram, "heightMap"), 0)

        glUniform3f(glGetUniformLocation(self.stockTopProgram, "stockMin"), STOCK_MIN_X, STOCK_MIN_Y, STOCK_MIN_Z)
        glUniform3f(glGetUniformLocation(self.stockTopProgram, "stockMax"), STOCK_MAX_X, STOCK_MAX_Y, STOCK_MAX_Z)
        glUniform1f(glGetUniformLocation(self.stockTopProgram, "meshResolution"), MESH_RES)

        uvmin, uvmax = self.getStockVisibleArea()
        glUniform2f(glGetUniformLocation(self.stockTopProgram, "uvmin"), uvmin.x, uvmin.y)
        glUniform2f(glGetUniformLocation(self.stockTopProgram, "uvmax"), uvmax.x, uvmax.y)

        light1dir = normalize(inverse(MVP) * vec4(1.0, -0.25, -1.0, 0)).xyz
        light2dir = normalize(inverse(MVP) * vec4(-0.5, -0.125, -0.5, 0)).xyz
        
        glUniform3fv(glGetUniformLocation(program=self.stockTopProgram, name="light1dir"), 1, value_ptr(light1dir))
        glUniform3fv(glGetUniformLocation(program=self.stockTopProgram, name="light2dir"), 1, value_ptr(light2dir))

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.stockTopEBO)
        size = glGetBufferParameteriv(GL_ELEMENT_ARRAY_BUFFER, GL_BUFFER_SIZE) // 4
        glDrawElements(GL_TRIANGLES, size, GL_UNSIGNED_INT, None)

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
    
    def drawStockBottom(self):
        self._make_current()

        glUseProgram(self.stockBottomProgram)
        glBindBuffer(GL_ARRAY_BUFFER, self.stockBottomVBO)
        PARAMETERS_PER_VERTEX = 1
        glVertexAttribPointer(glGetAttribLocation(self.stockBottomProgram, "index"), 1, GL_FLOAT, GL_FALSE, PARAMETERS_PER_VERTEX*4, c_void_p(0*4))
        glEnableVertexAttribArray(glGetAttribLocation(self.stockBottomProgram, "index"))

        MVP = self.PMatrix * self.MVMatrix
        mv_loc = glGetUniformLocation(program=self.stockBottomProgram, name="MVP")
        glUniformMatrix4fv(mv_loc, 1, False, value_ptr(MVP))

        glActiveTexture(GL_TEXTURE0)

        glBindTexture(GL_TEXTURE_2D, self.textures[0])

        glUniform1i(glGetUniformLocation(self.stockBottomProgram, "heightMap"), 0)

        glUniform3f(glGetUniformLocation(self.stockBottomProgram, "stockMin"), STOCK_MIN_X, STOCK_MIN_Y, STOCK_MIN_Z)
        glUniform3f(glGetUniformLocation(self.stockBottomProgram, "stockMax"), STOCK_MAX_X, STOCK_MAX_Y, STOCK_MAX_Z)

        light1dir = normalize(inverse(MVP) * vec4(1.0, -0.25, -1.0, 0)).xyz
        light2dir = normalize(inverse(MVP) * vec4(-0.5, -0.125, -0.5, 0)).xyz
        
        glUniform3fv(glGetUniformLocation(program=self.stockBottomProgram, name="light1dir"), 1, value_ptr(light1dir))
        glUniform3fv(glGetUniformLocation(program=self.stockBottomProgram, name="light2dir"), 1, value_ptr(light2dir))

        glDrawArrays(GL_TRIANGLES, 0, 6)

        glBindBuffer(GL_ARRAY_BUFFER, 0)
    
    def drawStockSide(self, side: int):
        # Side -> 1: up, 2: down, 3: left, 4: right
        # p1 and p2 -> vertices of the side surface

        self._make_current()

        glUseProgram(self.stockSideProgram)
        glBindBuffer(GL_ARRAY_BUFFER, self.stockSideVBO)
        PARAMETERS_PER_VERTEX = 1
        glVertexAttribPointer(glGetAttribLocation(self.stockSideProgram, "index"), 1, GL_FLOAT, GL_FALSE, PARAMETERS_PER_VERTEX*4, c_void_p(0*4))
        glEnableVertexAttribArray(glGetAttribLocation(self.stockSideProgram, "index"))

        MVP = self.PMatrix * self.MVMatrix
        mv_loc = glGetUniformLocation(program=self.stockSideProgram, name="MVP")
        glUniformMatrix4fv(mv_loc, 1, False, value_ptr(MVP))

        glActiveTexture(GL_TEXTURE0)

        glBindTexture(GL_TEXTURE_2D, self.textures[0])

        glUniform1i(glGetUniformLocation(self.stockSideProgram, "heightMap"), 0)

        glUniform1f(glGetUniformLocation(self.stockSideProgram, "side"), float(side))

        if side == 1:
            p1 = vec3(STOCK_MIN_X, STOCK_MAX_Y, STOCK_MIN_Z)
            p2 = vec3(STOCK_MAX_X, STOCK_MAX_Y, STOCK_MAX_Z)
        elif side == 2:
            p1 = vec3(STOCK_MIN_X, STOCK_MIN_Y, STOCK_MIN_Z)
            p2 = vec3(STOCK_MAX_X, STOCK_MIN_Y, STOCK_MAX_Z)
        elif side == 3:
            p1 = vec3(STOCK_MIN_X, STOCK_MIN_Y, STOCK_MIN_Z)
            p2 = vec3(STOCK_MIN_X, STOCK_MAX_Y, STOCK_MAX_Z)
        elif side == 4:
            p1 = vec3(STOCK_MAX_X, STOCK_MIN_Y, STOCK_MIN_Z)
            p2 = vec3(STOCK_MAX_X, STOCK_MAX_Y, STOCK_MAX_Z)
        else:
            return

        glUniform3f(glGetUniformLocation(self.stockSideProgram, "p1"), p1.x, p1.y, p1.z)
        glUniform3f(glGetUniformLocation(self.stockSideProgram, "p2"), p2.x, p2.y, p2.z)

        light1dir = normalize(inverse(MVP) * vec4(1.0, -0.25, -1.0, 0)).xyz
        light2dir = normalize(inverse(MVP) * vec4(-0.5, -0.125, -0.5, 0)).xyz
        
        glUniform3fv(glGetUniformLocation(program=self.stockSideProgram, name="light1dir"), 1, value_ptr(light1dir))
        glUniform3fv(glGetUniformLocation(program=self.stockSideProgram, name="light2dir"), 1, value_ptr(light2dir))

        glDrawArrays(GL_TRIANGLES, 0, 6)

        glBindBuffer(GL_ARRAY_BUFFER, 0)
    
    def getStockVisibleArea(self):
        if self.viewAngle(vec3(0, 0, 1)) == 90:
            return vec2(0, 0), vec2(1, 1)
        
        # Project the 4 corners of the canvas to the stock upper surface
        bl_up = self.canvas2WorldPlane(vec2(-1, -1), vec3(0, 0, 1), vec3(0, 0, STOCK_MAX_Z), 0)
        br_up = self.canvas2WorldPlane(vec2(1, -1), vec3(0, 0, 1), vec3(0, 0, STOCK_MAX_Z), 0)
        ul_up = self.canvas2WorldPlane(vec2(-1, 1), vec3(0, 0, 1), vec3(0, 0, STOCK_MAX_Z), 0)
        ur_up = self.canvas2WorldPlane(vec2(1, 1), vec3(0, 0, 1), vec3(0, 0, STOCK_MAX_Z), 0)

        # Project the 4 corners of the canvas to the stock lower surface
        bl_lo = self.canvas2WorldPlane(vec2(-1, -1), vec3(0, 0, 1), vec3(0, 0, STOCK_MIN_Z), 0)
        br_lo = self.canvas2WorldPlane(vec2(1, -1), vec3(0, 0, 1), vec3(0, 0, STOCK_MIN_Z), 0)
        ul_lo = self.canvas2WorldPlane(vec2(-1, 1), vec3(0, 0, 1), vec3(0, 0, STOCK_MIN_Z), 0)
        ur_lo = self.canvas2WorldPlane(vec2(1, 1), vec3(0, 0, 1), vec3(0, 0, STOCK_MIN_Z), 0)

        xmin = min(bl_up.x, br_up.x, ul_up.x, ur_up.x, bl_lo.x, br_lo.x, ul_lo.x, ur_lo.x)
        xmax = max(bl_up.x, br_up.x, ul_up.x, ur_up.x, bl_lo.x, br_lo.x, ul_lo.x, ur_lo.x)
        ymin = min(bl_up.y, br_up.y, ul_up.y, ur_up.y, bl_lo.y, br_lo.y, ul_lo.y, ur_lo.y)
        ymax = max(bl_up.y, br_up.y, ul_up.y, ur_up.y, bl_lo.y, br_lo.y, ul_lo.y, ur_lo.y)

        uvminx = max(0, (xmin - STOCK_MIN_X) / (STOCK_MAX_X - STOCK_MIN_X))
        uvmaxx = min(1, (xmax - STOCK_MIN_X) / (STOCK_MAX_X - STOCK_MIN_X))
        uvminy = max(0, (ymin - STOCK_MIN_Y) / (STOCK_MAX_Y - STOCK_MIN_Y))
        uvmaxy = min(1, (ymax - STOCK_MIN_Y) / (STOCK_MAX_Y - STOCK_MIN_Y))

        return vec2(uvminx, uvminy), vec2(uvmaxx, uvmaxy)
    
    def viewAngle(self, planeNormal : vec3) -> float:
        """
        Return the angle between the current view and a specific plane normal in 3D
        """

        MVPinv = inverse(self.PMatrix * self.MVMatrix)

        # We define a line perpendicular to the canvas
        p1 = (MVPinv * vec4(0, 0, 0, 1)).xyz
        p2 = (MVPinv * vec4(0, 0, 1, 1)).xyz

        v12 = p2 - p1

        return numpy.rad2deg(numpy.arccos(abs(dot(normalize(v12), planeNormal))))

    def canvas2WorldPlane(self, coords_uv: vec2, planeNormal : vec3, planePoint : vec3, thresholdAngle = 20.): # -> vec3 | None:
        # return the intersection of a vector perpendicular to the screen, at uv coordinates in the canvas (-1 -> 1), with a plane in world coordinates

        MVPinv = inverse(self.PMatrix * self.MVMatrix)

        # We define a line perpendicular to the canvas
        p1 = (MVPinv * vec4(coords_uv, 0, 1)).xyz
        p2 = (MVPinv * vec4(coords_uv, 1, 1)).xyz
        
        v12 = p2 - p1

        # If we are too parallel to the plane, return None
        angle = 90 - numpy.rad2deg(numpy.arccos(abs(dot(normalize(v12), planeNormal))))
        if angle == 0 or angle < abs(thresholdAngle):
            return None

        n = normalize(planeNormal)
        denom = dot(n, v12)
        t = dot(n, planePoint - p1) / denom

        intersection = p1 + v12 * t

        return intersection
    
    def updateStockMaterialBuffers(self, nx, ny):
        # Vertices (normalized from 0. to 1.)

        xval, yval = numpy.indices((nx, ny), dtype=numpy.float32)
        xval /= nx - 1
        yval /= ny - 1
        vertices = numpy.stack([xval.T.ravel(), yval.T.ravel()], axis=1)

        self._make_current()
              
        glBindBuffer(GL_ARRAY_BUFFER, self.stockTopVBO)     
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        # Indices

        i = numpy.arange(nx - 1)
        j = numpy.arange(ny - 1)

        I, J = numpy.meshgrid(i, j)

        bl = J * nx + I
        br = bl + 1
        tl = bl + nx
        tr = tl + 1

        indices = numpy.stack([
            bl, br, tr,
            bl, tr, tl
        ], axis=-1).ravel()

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.stockTopEBO)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)
    
    def millSegment(self, p1: vec3, p2: vec3, toolType: int, diameter: float):
        """
        Single-pass, scissored milling update.

        The fragment shader reads the source height texture and writes
        the complete destination value for every pixel in the scissor
        rectangle. Pixels outside the actual cutter footprint simply
        write oldHeight unchanged.
        """
        self._make_current()

        # Cutter bounding box in workpiece coordinates.
        min_x = max(STOCK_MIN_X, min(p1.x - diameter / 2., p2.x - diameter / 2))
        max_x = min(STOCK_MAX_X, max(p1.x + diameter / 2., p2.x + diameter / 2))
        min_y = max(STOCK_MIN_Y, min(p1.y - diameter / 2., p2.y - diameter / 2))
        max_y = min(STOCK_MAX_Y, max(p1.y + diameter / 2., p2.y + diameter / 2))

        if min_x >= max_x or min_y >= max_y:
            return

        work_w = STOCK_MAX_X - STOCK_MIN_X
        work_h = STOCK_MAX_Y - STOCK_MIN_Y

        # Convert physical XY to texture/framebuffer pixels.
        sx0 = int(math.floor((min_x - STOCK_MIN_X) / work_w * HEIGHTMAP_RES))
        sx1 = int(math.ceil((max_x - STOCK_MIN_X) / work_w * HEIGHTMAP_RES))

        sy0 = int(math.floor((min_y - STOCK_MIN_Y) / work_h * HEIGHTMAP_RES))
        sy1 = int(math.ceil((max_y - STOCK_MIN_Y) / work_h * HEIGHTMAP_RES))

        sx0 = max(0, min(HEIGHTMAP_RES - 1, sx0))
        sy0 = max(0, min(HEIGHTMAP_RES - 1, sy0))
        sx1 = max(sx0 + 1, min(HEIGHTMAP_RES, sx1))
        sy1 = max(sy0 + 1, min(HEIGHTMAP_RES, sy1))

        width = sx1 - sx0
        height = sy1 - sy0

        # Destination FBO.
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbos[1])

        glDrawBuffer(GL_COLOR_ATTACHMENT0)

        glViewport(0, 0, HEIGHTMAP_RES, HEIGHTMAP_RES)

        # Rasterization is restricted to the cutter's bounding box.
        glEnable(GL_SCISSOR_TEST)
        glScissor(sx0, sy0, width, height)

        glDisable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        glDisable(GL_CULL_FACE)

        glUseProgram(self.millProgram)

        # Source height map.
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.textures[0])

        glBindBuffer(GL_ARRAY_BUFFER, self.millVBO)
        PARAMETERS_PER_VERTEX = 2
        glVertexAttribPointer(glGetAttribLocation(self.millProgram, "pos"), 2, GL_FLOAT, GL_FALSE, PARAMETERS_PER_VERTEX*4, c_void_p(0*4))
        glEnableVertexAttribArray(glGetAttribLocation(self.millProgram, "pos"))

        glUniform1i(glGetUniformLocation(self.millProgram, "heightMap"), 0)
        glUniform3f(glGetUniformLocation(self.millProgram, "pA"), p1.x, p1.y, p1.z)
        glUniform3f(glGetUniformLocation(self.millProgram, "pB"), p2.x, p2.y, p2.z)
        glUniform1f(glGetUniformLocation(self.millProgram, "toolRadius"), diameter / 2.)
        glUniform1i(glGetUniformLocation(self.millProgram, "toolType"), toolType) # TODO: tool type as argument
        glUniform2f(glGetUniformLocation(self.millProgram, "workMin"), STOCK_MIN_X, STOCK_MIN_Y)
        glUniform2f(glGetUniformLocation(self.millProgram, "workMax"), STOCK_MAX_X, STOCK_MAX_Y)

        glDrawArrays(GL_TRIANGLES, 0, 3)

        glBindBuffer(GL_ARRAY_BUFFER, 0)

        glUseProgram(0)
        glDisable(GL_SCISSOR_TEST)

        # Copy the milled region to the source framebuffer
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.fbos[1])
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.fbos[0])

        glBlitFramebuffer(
            sx0, sy0,
            sx1, sy1,
            sx0, sy0,
            sx1, sy1,
            GL_COLOR_BUFFER_BIT,
            GL_NEAREST
        )

        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def runSimulation(self):
        self.reset()

        lines16 = numpy.reshape(self.cncCanvas.pathVertices, (-1, 16))

        millType = MILL_TYPES[self.millType.get()]
        D = self.millDiameter.get()

        for line in lines16:
            p1 = vec3(line[1:4])
            p2 = vec3(line[9:12])
        
            self.millSegment(p1, p2, millType, D)
        self.queueDraw()
    
    def fit2Screen(self, event=None):
        """
        Zoom to Fit to Screen
        """
        
        upVector = inverse(self.MVMatrix) * vec4(0, 1, 0, 0)
        depthVector = inverse(self.MVMatrix) * vec4(0, 0, 1, 0)
        
        modelCenter = vec3((STOCK_MIN_X + STOCK_MAX_X) / 2., (STOCK_MIN_Y + STOCK_MAX_Y) / 2., (STOCK_MIN_Z + STOCK_MAX_Z) / 2.)
        modelSize = math.sqrt(pow(STOCK_MAX_X - STOCK_MIN_X, 2) + pow(STOCK_MAX_Y - STOCK_MIN_Y, 2) + pow(STOCK_MIN_Z - STOCK_MAX_Z, 2))

        self.MVMatrix = lookAt(
            modelCenter + depthVector.xyz, # eye
            modelCenter, # target
            upVector.xyz # up
            )
        # Adjust the Projection Matrix
        width = self.winfo_width()
        height = self.winfo_height()
        
        self.zoom = min(width, height) / modelSize
        
        self.PMatrix = ortho(-width / 2.0 / self.zoom, 
                             width / 2.0 / self.zoom, 
                             -height / 2.0 / self.zoom,
                             height / 2.0 / self.zoom, 
                             -10000,
                             10000)

        self.queueDraw()

class SimCanvasFrame(Frame):
    def __init__(self, master, app, *kw, **kwargs):
        Frame.__init__(self, master, *kw, **kwargs)
        self.app = app

        self.view = StringVar()

        toolbar = Frame(self, relief=RAISED)
        toolbar.pack(side='top', fill='x')

        # Ensure the Frame exists at the OS level before OpenGL initializes
        self.pack(side='top', fill='both', expand=True)
        self.update()

        # --- SIM Canvas ---
        self.canvas = SimCanvas(self, app, takefocus=True, background="White")

        # --- SIM Panel ---

        simPanel = Frame(self, width=200)
        simPanel.pack(side='left', fill='y')
        simPanel.pack_propagate(False)

        lframe = LabelFrame(simPanel, text=_("Stock dimensions"), foreground="DarkBlue")
        lframe.pack(side='top', fill='x')

        row, col = 0, 0
        # Empty
        col += 1
        Label(lframe, text=_("Min")).grid(row=row, column=col, sticky=EW)
        col += 1
        Label(lframe, text=_("Max")).grid(row=row, column=col, sticky=EW)

        # --- X ---
        row += 1
        col = 0
        Label(lframe, text=_("X:")).grid(row=row, column=col, sticky=E)
        col += 1
        self.stockXmin = tkExtra.FloatEntry(lframe, background=tkExtra.GLOBAL_CONTROL_BACKGROUND, width=5)
        self.stockXmin.grid(row=row, column=col, sticky=EW)
        tkExtra.Balloon.set(self.stockXmin, _("X minimum"))
        self.addWidget(self.stockXmin)

        col += 1
        self.stockXmax = tkExtra.FloatEntry(lframe, background=tkExtra.GLOBAL_CONTROL_BACKGROUND, width=5)
        self.stockXmax.grid(row=row, column=col, sticky=EW)
        tkExtra.Balloon.set(self.stockXmax, _("X maximum"))
        self.addWidget(self.stockXmax)

        # --- Y ---
        row += 1
        col = 0
        Label(lframe, text=_("Y:")).grid(row=row, column=col, sticky=E)
        col += 1
        self.stockYmin = tkExtra.FloatEntry(lframe, background=tkExtra.GLOBAL_CONTROL_BACKGROUND, width=5)
        self.stockYmin.grid(row=row, column=col, sticky=EW)
        tkExtra.Balloon.set(self.stockYmin, _("Y minimum"))
        self.addWidget(self.stockYmin)

        col += 1
        self.stockYmax = tkExtra.FloatEntry(lframe, background=tkExtra.GLOBAL_CONTROL_BACKGROUND, width=5)
        self.stockYmax.grid(row=row, column=col, sticky=EW)
        tkExtra.Balloon.set(self.stockYmax, _("Y maximum"))
        self.addWidget(self.stockYmax)

        # --- Z ---
        row += 1
        col = 0
        Label(lframe, text=_("Z:")).grid(row=row, column=col, sticky=E)
        col += 1
        self.stockZmin = tkExtra.FloatEntry(lframe, background=tkExtra.GLOBAL_CONTROL_BACKGROUND, width=5)
        self.stockZmin.grid(row=row, column=col, sticky=EW)
        tkExtra.Balloon.set(self.stockZmin, _("Z minimum"))
        self.addWidget(self.stockZmin)

        col += 1
        self.stockZmax = tkExtra.FloatEntry(lframe, background=tkExtra.GLOBAL_CONTROL_BACKGROUND, width=5)
        self.stockZmax.grid(row=row, column=col, sticky=EW)
        tkExtra.Balloon.set(self.stockZmax, _("Z maximum"))
        self.addWidget(self.stockZmax)

        # --- Refresh button ---
        row += 1
        col = 1
        bRefresh = Button(lframe, text=_("Refresh"), compound=LEFT, command=self.updateStockSize, image=Utils.icons["refresh"], padx=2, pady=1)
        bRefresh.grid(row=row, column=col, columnspan=2, sticky=EW)
        self.addWidget(bRefresh)

        lframe.grid_columnconfigure(1, weight=1)
        lframe.grid_columnconfigure(2, weight=1)

        # --- End Mill data ---

        lframe = LabelFrame(simPanel, text=_("End Mill"), foreground="DarkBlue")
        lframe.pack(side='top', fill='x', pady=10)
        self.millType = tkinter.OptionMenu(lframe, self.canvas.millType, "Flat", "Ball")
        #self.millType = tkExtra.Combobox(lframe, True, background=tkExtra.GLOBAL_CONTROL_BACKGROUND, textvariable=self.canvas.millType)
        #self.millType.fill(["Flat", "Ball"])
        #self.millType.set("Flat")
        self.millType.pack(side='top', fill='x')
        tkExtra.Balloon.set(self.millType, _("Type of End Mill"))

        lineFrame = Frame(lframe)
        lineFrame.pack(side='top', fill='x', pady=10)

        Label(lineFrame, text=_("Diameter:")).pack(side='left')
        self.millDiameter = tkExtra.FloatEntry(lineFrame, background=tkExtra.GLOBAL_CONTROL_BACKGROUND, width=10, textvariable=self.canvas.millDiameter)
        self.millDiameter.pack(side='left', fill='x', expand=True, padx=5)
        tkExtra.Balloon.set(self.millDiameter, _("Mill Diameter"))
        self.addWidget(self.millDiameter)

        # Pack the canvas
        self.canvas.pack(side='top', fill='both', expand=True)

        self.createCanvasToolbar(toolbar)

        self.loadConfig()
        self.updateStockSize()

    # ----------------------------------------------------------------------
    def addWidget(self, widget):
        self.app.widgets.append(widget)

    # ----------------------------------------------------------------------
    # SimCanvas toolbar
    # ----------------------------------------------------------------------
    def createCanvasToolbar(self, toolbar):
        b = Button(toolbar, image=Utils.icons["reset"], command=self.canvas.reset)
        b.pack(side=LEFT)
        tkExtra.Balloon.set(b, _("Reset Stock"))

        b = Button(toolbar, image=Utils.icons["start"], command=self.canvas.runSimulation)
        b.pack(side=LEFT)
        tkExtra.Balloon.set(b, _("Run simulation"))

    # ----------------------------------------------------------------------
    def redraw(self, event=None):
        self.canvas.reset()
        self.event_generate("<<ViewChange>>")

    # ----------------------------------------------------------------------
    def viewChange(self, a=None, b=None, c=None):
        view = VIEWS.index(self.view.get())

        self.canvas.MVMatrix = mat4x4(self.canvas.MVMatrix)

        if view == 0:
            self.canvas.MVMatrix = lookAt(
                vec3(0, 0, 1),
                vec3(0, 0, 0),
                vec3(0, 1, 0))
        elif view == 1:
            self.canvas.MVMatrix = lookAt(
                vec3(0, -1, 0),
                vec3(0, 0, 0),
                vec3(0, 0, 1))
        elif view == 2:
            self.canvas.MVMatrix = lookAt(
                vec3(1, 0, 0),
                vec3(0, 0, 0),
                vec3(0, 0, 1))
        elif view == 3:
            self.canvas.MVMatrix = lookAt(
                vec3(1, -1, 1),
                vec3(0, 0, 0),
                vec3(0, 0, 1))
        elif view == 4:
            self.canvas.MVMatrix = lookAt(
                vec3(-1, -1, 1),
                vec3(0, 0, 0),
                vec3(0, 0, 1))
        elif view == 5:
            self.canvas.MVMatrix = lookAt(
                vec3(-1, 1, 1),
                vec3(0, 0, 0),
                vec3(0, 0, 1))
        
        #self.event_generate("<<ViewChange>>")
        self.canvas.fit2Screen()

    # ----------------------------------------------------------------------
    def viewXY(self, event=None):
        self.view.set(VIEWS[VIEW_XY])

    # ----------------------------------------------------------------------
    def viewXZ(self, event=None):
        self.view.set(VIEWS[VIEW_XZ])

    # ----------------------------------------------------------------------
    def viewYZ(self, event=None):
        self.view.set(VIEWS[VIEW_YZ])

    # ----------------------------------------------------------------------
    def viewISO1(self, event=None):
        self.view.set(VIEWS[VIEW_ISO1])

    # ----------------------------------------------------------------------
    def viewISO2(self, event=None):
        self.view.set(VIEWS[VIEW_ISO2])

    # ----------------------------------------------------------------------
    def viewISO3(self, event=None):
        self.view.set(VIEWS[VIEW_ISO3])

    def loadConfig(self):
        global MILL_TYPE, MILL_DIAMETER

        self.stockXmin.set(Utils.getFloat("Simulation", "xmin", STOCK_MIN_X))
        self.stockXmax.set(Utils.getFloat("Simulation", "xmax", STOCK_MAX_X))
        self.stockYmin.set(Utils.getFloat("Simulation", "ymin", STOCK_MIN_Y))
        self.stockYmax.set(Utils.getFloat("Simulation", "ymax", STOCK_MAX_Y))
        self.stockZmin.set(Utils.getFloat("Simulation", "zmin", STOCK_MIN_Z))
        self.stockZmax.set(Utils.getFloat("Simulation", "zmax", STOCK_MAX_Z))

        self.canvas.millType.set(Utils.getStr("Simulation", "milltype", "Flat"))

        self.canvas.millDiameter.set(Utils.getFloat("Simulation", "milldiameter", 6.0))

    def saveConfig(self):
        Utils.addSection("Simulation")

        Utils.setFloat("Simulation", "xmin", self.stockXmin.get())
        Utils.setFloat("Simulation", "xmax", self.stockXmax.get())
        Utils.setFloat("Simulation", "ymin", self.stockYmin.get())
        Utils.setFloat("Simulation", "ymax", self.stockYmax.get())
        Utils.setFloat("Simulation", "zmin", self.stockZmin.get())
        Utils.setFloat("Simulation", "zmax", self.stockZmax.get())
        Utils.setStr("Simulation", "milltype", self.canvas.millType.get())
        Utils.setFloat("Simulation", "millDiameter", self.canvas.millDiameter.get())

    def updateStockSize(self):
        try:
            xmin = float(self.stockXmin.get())
            xmax = float(self.stockXmax.get())
            ymin = float(self.stockYmin.get())
            ymax = float(self.stockYmax.get())
            zmin = float(self.stockZmin.get())
            zmax = float(self.stockZmax.get())
        except:
            messagebox.showinfo("Warning", "Please fill in all the stock dimensions")
            return
        
        if xmax <= xmin:
            messagebox.showinfo("Warning", "Xmax must be greater than Xmin")
            return
        
        if ymax <= ymin:
            messagebox.showinfo("Warning", "Ymax must be greater than Ymin")
            return
        
        if zmax <= zmin:
            messagebox.showinfo("Warning", "Zmax must be greater than Zmin")
            return
        
        global STOCK_MIN_X, STOCK_MAX_X, STOCK_MIN_Y, STOCK_MAX_Y, STOCK_MIN_Z, STOCK_MAX_Z

        STOCK_MIN_X = xmin
        STOCK_MAX_X = xmax
        STOCK_MIN_Y = ymin
        STOCK_MAX_Y = ymax
        STOCK_MIN_Z = zmin
        STOCK_MAX_Z = zmax

        self.canvas.reset()
        self.canvas.fit2Screen()

