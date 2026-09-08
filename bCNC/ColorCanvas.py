import math
import sys
from tkinter_gl import GLCanvas

import OpenGL

if sys.platform == 'linux':
    # PyOpenGL is broken with wayland:
    OpenGL.setPlatform('x11')

from OpenGL.GL import *
import os

import tkinter

import bmath
import Camera
import tkExtra
import Utils
from CNC import CNC, Probe
import CNCCanvas


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

# =============================================================================
# Simulation canvas
# =============================================================================
class ColorCanvas(GLCanvas):
    profile = 'legacy'
    
    def __init__(self, master, app, *kw, **kwargs):
        super().__init__(master)

        self.app = app
        self._drawRequested = False

        self._make_current()

        self.queueDraw()

    def queueDraw(self):
        if self._drawRequested:
            return
        
        self._drawRequested = True
        
        self.after('idle', self.draw)
    
    def draw(self):        
        self._make_current()
        width, height = self.winfo_width(), self.winfo_height()
        
        # Check readiness of the buffer
        if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            self._drawRequested = False
            self.queueDraw()
            return

        glViewport(0, 0, width, height)

        glClearColor(1, 0, 0, 1)        
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT) # type: ignore
        
        self.swap_buffers()
        
        self._drawRequested = False

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