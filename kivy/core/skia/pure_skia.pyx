import os
from libc.stdint cimport uint8_t
from libcpp.memory cimport unique_ptr

from kivy.graphics.cgl import cgl_get_backend_name

# cdef extern from "<utility>" namespace "std":
#     cdef cppclass pair[T1, T2]:
#         T1 first
#         T2 second

cdef extern from "include/core/SkRefCnt.h":
    cdef cppclass sk_sp[T]:
        sk_sp() except +
        sk_sp(T*) except +
        
cdef extern from "include/core/SkSurface.h":
    cdef cppclass SkSurface

cdef extern from "include/core/SkCanvas.h":
    cdef cppclass SkCanvas

cdef extern from "include/gpu/ganesh/GrDirectContext.h":
    cdef cppclass GrDirectContext


cdef extern from "pure_skia_implem.cpp":
    ctypedef struct SkiaSurfaceData:
        sk_sp[SkSurface] surface
        SkCanvas* canvas
        sk_sp[GrDirectContext] context
    
    void initialize_gl_interface(bint use_angle)
    
    SkiaSurfaceData createSkiaSurfaceData(int width, int height) nogil

    void clearCanvas(SkCanvas *canvas, sk_sp[GrDirectContext] context, uint8_t r, uint8_t g, uint8_t b, uint8_t a) nogil
    void drawCircle(SkCanvas *canvas, sk_sp[GrDirectContext] context, float x, float y, float width, float height, int segments, float angle_start, float angle_end) nogil
    void flushAndSubmit(sk_sp[GrDirectContext] context) nogil


# initialize the interface for the gl backend. The interface has similar usage to kivy's "cgl.<gl function>".
# but it is accessed through interface->fFunctions.f<gl function>
initialize_gl_interface("angle" in cgl_get_backend_name())



cdef class SkiaSurface:
    
    cdef sk_sp[SkSurface] surface
    cdef SkCanvas *canvas
    cdef sk_sp[GrDirectContext] context

    def __init__(self, int width, int height):
        cdef SkiaSurfaceData surface_data = createSkiaSurfaceData(width, height)
        self.surface = surface_data.surface
        self.canvas = surface_data.canvas
        self.context = surface_data.context

    cpdef void clear_canvas(self, uint8_t r, uint8_t g, uint8_t b, uint8_t a):
        with nogil:
            clearCanvas(self.canvas, self.context, r, g, b, a)


    cpdef draw_circle(self, float x, float y, float width, float height, int segments, float angle_start, float angle_end):
        with nogil:
            drawCircle(self.canvas, self.context, x, y, width, height, segments, angle_start, angle_end)

    cpdef context_flush_and_submit(self):
        with nogil:
            flushAndSubmit(self.context)
