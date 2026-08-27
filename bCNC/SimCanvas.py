import math
import time
import sys
from numpy import deg2rad
from tkinter_gl import GLCanvas

import OpenGL

if sys.platform == 'linux':
    # PyOpenGL is broken with wayland:
    OpenGL.setPlatform('x11')

from OpenGL.GL import *
from ctypes import c_void_p
from pyglm.glm import mat4x4, mat3x3, ortho, identity, value_ptr, inverse, translate, rotate, vec2, vec3, vec4, inverse, normalize, lookAt, dot, cross, distance, length2
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
    Button,
    Canvas,
    Checkbutton,
    Frame,
    Label,
    Radiobutton,
    Scrollbar,
    OptionMenu,
    Toplevel
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

def mouseCursor(action):
    return MOUSE_CURSOR.get(action, DEF_CURSOR)

# =============================================================================
# Simulation canvas
# =============================================================================
class SimCanvas(GLCanvas):
    def __init__(self, master, app, *kw, **kwargs):
        super().__init__(master)

        profile = 'legacy'

        self.app = app

        self.windowing_system = self.app.call('tk', 'windowingsystem')

        # Canvas binding
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

        # OPENGL vars
        self.MVMatrix = identity(mat4x4) # Model View Matrix
        self.PMatrix = ortho(-100, 100, -100, 100, -10000, 10000) # Projection matrix. Updated on resize

        self._drawRequested = False
        self._x = self._y = 0
        self._xp = self._yp = 0
        self._mouseAction = None
        self.__tzoom = 1.0  # delayed zoom (temporary)
        self.zoom = 1.

        self.initGL()
    
    def rgb8(self, colorName):
        return (numpy.array(self.winfo_rgb(colorName)) * 255. / 65535.).astype(int)
    
    def configureEvent(self, event):
        self.draw()
    
    def midClick(self, event):
        self._x = self._xp = event.x
        self._y = self._yp = event.y
    
    def rightClick(self, event):
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
        # change the rotation center to the closest point of that line to the point where the user clicked
        if self._mouseAction != ACTION_PAN and self._mouseAction != ACTION_ZOOM:
            #newRotationCenter, pointType = self.snapPoint(vec2(event.x, event.y))
            newRotationCenter = None
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
        self.make_current()
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
        self.drawStockMaterial()

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
        glUseProgram(self.backgroundProgram)      
        glBindBuffer(GL_ARRAY_BUFFER, self.backgroundVBO)
        
        vertices = numpy.array([1, 2, 3, 1, 3, 4], dtype=numpy.float32)
        
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        # ----- STOCK MATERIAL PROGRAM ------
        # Vertex Shader code
        with open(CNCCanvas.openglFolder + "StockMaterialVS.shd", "r") as file:
            StockMaterialVSCode = file.read()

        # Fragment Shader code
        with open(CNCCanvas.openglFolder + "StockMaterialFS.shd", "r") as file:
            StockMaterialFSCode = file.read()

        self.stockMaterialProgram = self.createProgram(StockMaterialVSCode, StockMaterialFSCode)

        # Create a Vertex Buffer Object (VBO)
        self.stockMaterialVBO = glGenBuffers(1)

        # Create an Element Buffer Object (EBO)
        self.stockMaterialEBO = glGenBuffers(1)

        # Create the stock material vertices and indices
        self.updateStockMaterialBuffers(1000, 1000)
        
        # Create the height map
        self.updateHeightMap(10000, 10000)

    def drawBackground(self):
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

    def drawStockMaterial(self):
        glUseProgram(self.stockMaterialProgram)
        glBindBuffer(GL_ARRAY_BUFFER, self.stockMaterialVBO)
        PARAMETERS_PER_VERTEX = 2
        glVertexAttribPointer(glGetAttribLocation(self.stockMaterialProgram, "pos"), 2, GL_FLOAT, GL_FALSE, PARAMETERS_PER_VERTEX*4, c_void_p(0*4))
        glEnableVertexAttribArray(glGetAttribLocation(self.stockMaterialProgram, "pos"))

        MVP = self.PMatrix * self.MVMatrix
        mv_loc = glGetUniformLocation(program=self.stockMaterialProgram, name="MVP")
        glUniformMatrix4fv(mv_loc, 1, False, value_ptr(MVP))

        bottomleft = vec2(-100, -100)
        bottomleft_loc = glGetUniformLocation(program=self.stockMaterialProgram, name="bottomleft")
        glUniform2fv(bottomleft_loc, 1, value_ptr(bottomleft))

        size = vec2(200, 200)
        size_loc = glGetUniformLocation(program=self.stockMaterialProgram, name="size")
        glUniform2fv(size_loc, 1, value_ptr(size))

        light1dir = normalize(inverse(MVP) * vec4(1.0, -0.25, -1.0, 0)).xyz
        light2dir = normalize(inverse(MVP) * vec4(-0.5, -0.125, -0.5, 0)).xyz
        
        light1dir_loc = glGetUniformLocation(program=self.stockMaterialProgram, name="light1dir")
        glUniform3fv(light1dir_loc, 1, value_ptr(light1dir))
        light2dir_loc = glGetUniformLocation(program=self.stockMaterialProgram, name="light2dir")
        glUniform3fv(light2dir_loc, 1, value_ptr(light2dir))

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.stockMaterialEBO)
        size = glGetBufferParameteriv(GL_ELEMENT_ARRAY_BUFFER, GL_BUFFER_SIZE) // 4
        glDrawElements(GL_TRIANGLES, size, GL_UNSIGNED_INT, None)
    
    def updateStockMaterialBuffers(self, nx, ny):
        # Vertices (normalized from 0. to 1.)

        xval, yval = numpy.indices((nx, ny), dtype=numpy.float32)
        xval /= nx - 1
        yval /= ny - 1
        vertices = numpy.stack([xval.T.ravel(), yval.T.ravel()], axis=1)
              
        glBindBuffer(GL_ARRAY_BUFFER, self.stockMaterialVBO)     
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

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.stockMaterialEBO)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)

    def updateHeightMap(self, nx, ny):
        # Texture with a resolution of (nx, ny), to store the height of the stock material upper surface during milling
        pass


class SimCanvasFrame(Frame):
    def __init__(self, master, app, *kw, **kwargs):
        Frame.__init__(self, master, *kw, **kwargs)
        self.app = app

        self.draw_axes = BooleanVar()
        self.draw_grid = BooleanVar()
        self.draw_margin = BooleanVar()
        self.draw_probe = BooleanVar()
        self.draw_paths = BooleanVar()
        self.draw_rapid = BooleanVar()
        self.draw_workarea = BooleanVar()
        self.draw_camera = BooleanVar()
        self.view = StringVar()

        toolbar = Frame(self, relief=RAISED)
        toolbar.grid(row=0, column=0, sticky=EW)

        # Ensure the Frame exists at the OS level before OpenGL initializes
        self.pack(side='top', fill='both', expand=True)
        self.update()

        self.canvas = SimCanvas(self, app, takefocus=True, background="White")
        self.canvas.grid(row=1, column=0, sticky=NSEW)

        self.createCanvasToolbar(toolbar)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

    # ----------------------------------------------------------------------
    def addWidget(self, widget):
        self.app.widgets.append(widget)


    # ----------------------------------------------------------------------
    # Canvas toolbar FIXME XXX should be moved to CNCCanvas
    # ----------------------------------------------------------------------
    def createCanvasToolbar(self, toolbar):
        # -----------
        # Draw flags
        # -----------
        Label(toolbar, text=_("Draw:"),
              compound=LEFT).pack(
            side=LEFT  )
        Button(toolbar, text="+", command=self.canvas.draw).pack(side=LEFT)

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

    # ----------------------------------------------------------------------
    def toggleDrawFlag(self):
        self.canvas.draw_axes = self.draw_axes.get()
        self.canvas.draw_grid = self.draw_grid.get()
        self.canvas.draw_margin = self.draw_margin.get()
        self.canvas.draw_probe = self.draw_probe.get()
        self.canvas.draw_paths = self.draw_paths.get()
        self.canvas.draw_rapid = self.draw_rapid.get()
        self.canvas.draw_workarea = self.draw_workarea.get()
        self.event_generate("<<ViewChange>>")

    # ----------------------------------------------------------------------
    def drawAxes(self, value=None):
        if value is not None:
            self.draw_axes.set(value)
        self.canvas.draw_axes = self.draw_axes.get()
        self.canvas.queueDraw()

    # ----------------------------------------------------------------------
    def drawGrid(self, value=None):
        if value is not None:
            self.draw_grid.set(value)
        self.canvas.draw_grid = self.draw_grid.get()
        self.canvas.updateGrid()

    # ----------------------------------------------------------------------
    def drawMargin(self, value=None):
        if value is not None:
            self.draw_margin.set(value)
        self.canvas.draw_margin = self.draw_margin.get()
        self.canvas.updateMargin()

    # ----------------------------------------------------------------------
    def drawProbe(self, value=None):
        if value is not None:
            self.draw_probe.set(value)
        self.canvas.draw_probe = self.draw_probe.get()
        self.canvas.drawProbe()

    # ----------------------------------------------------------------------
    def drawWorkarea(self, value=None):
        if value is not None:
            self.draw_workarea.set(value)
        self.canvas.draw_workarea = self.draw_workarea.get()
        self.canvas.updateWorkArea()

    # ----------------------------------------------------------------------
    def drawCamera(self, value=None):
        if value is not None:
            self.draw_camera.set(value)
        if self.draw_camera.get():
            self.canvas.cameraOn()
        else:
            self.canvas.cameraOff()
            self.canvas.queueDraw()

    # ----------------------------------------------------------------------
    def drawTimeChange(self):
        global DRAW_TIME
        try:
            DRAW_TIME = int(self.drawTime.get())
        except ValueError:
            DRAW_TIME = 5 * 60
        self.viewChange()
