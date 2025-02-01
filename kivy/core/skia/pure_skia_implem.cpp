#include <cmath>
#include <memory>
#include <cstdio>

// Core Skia headers
#include "include/core/SkPathBuilder.h"
#include "include/core/SkBitmap.h"
#include "include/core/SkRRect.h"
#include "include/core/SkColorSpace.h"
#include "include/core/SkCanvas.h"
#include "include/core/SkSurface.h"
#include "include/core/SkImage.h"
#include "include/core/SkImageInfo.h"
#include "include/core/SkStream.h"
#include "modules/skottie/include/Skottie.h"

// Skia GPU headers
#include "include/gpu/ganesh/GrDirectContext.h"
#include "include/gpu/ganesh/gl/GrGLTypes.h"
#include "include/gpu/ganesh/SkSurfaceGanesh.h"
#include "include/gpu/ganesh/gl/GrGLBackendSurface.h"
#include "include/gpu/ganesh/GrBackendSurface.h"
#include "include/gpu/GpuTypes.h"
#include "include/gpu/ganesh/gl/GrGLInterface.h"
#include "include/gpu/ganesh/gl/GrGLDirectContext.h"
#include "src/gpu/ganesh/gl/GrGLDefines.h"
#include "src/gpu/ganesh/SurfaceDrawContext.h"
#include <include/gpu/ganesh/gl/GrGLAssembleInterface.h>

// Effects and filters
#include <include/effects/SkImageFilters.h>

// Kivy configuration (for build flags)
#include "config.h"

// angle
#if !defined(__APPLE__)
#include "SDL2/SDL_egl.h"
#endif

#if __USE_ANGLE_GL_BACKEND
    #include <EGL/egl.h>
    #ifndef GL_GLEXT_PROTOTYPES
    #define GL_GLEXT_PROTOTYPES
    #endif

    #include "angle_gl.h"
#endif

sk_sp<const GrGLInterface> gl_interface;

void initialize_gl_interface(bool use_angle)
{
    // angle
    #if !defined(__APPLE__) || __USE_ANGLE_GL_BACKEND
    if (use_angle)
    {
        printf("Using ANGLE GL backend.\n");
        gl_interface = GrGLMakeAssembledInterface(
            nullptr,
            [](void *ctx, const char name[]) -> GrGLFuncPtr
            { return eglGetProcAddress(name); });
    }
    else
    #endif
    {
        printf("Using native GL implementation.\n");
        gl_interface = GrGLMakeNativeInterface();
    }

    // Validate the GL interface to ensure it is valid
    if (!gl_interface->validate())
    {
        printf("GL interface is invalid.\n");
    }
}

// Structure to encapsulate Skia surface data
struct SkiaSurfaceData
{
    sk_sp<SkSurface> surface;
    SkCanvas *canvas;
    sk_sp<GrDirectContext> context;
};

SkiaSurfaceData createSkiaSurfaceData(int width, int height)
{

    SkSurfaceProps props;
    sk_sp<GrDirectContext> context = GrDirectContexts::MakeGL(gl_interface);
    if (!context)
    {
        printf("Failed to create GrContext.\n");
    }

    // Framebuffer configuration
    GrGLFramebufferInfo framebufferInfo;
    framebufferInfo.fFBOID = 0;
    framebufferInfo.fFormat = GR_GL_RGBA8;

    // Backend render target configuration
    GrBackendRenderTarget backendRenderTarget = GrBackendRenderTargets::MakeGL(
        width, height, 0, 0, framebufferInfo);

    // Create Skia surface
    sk_sp<SkColorSpace> colorSpace = SkColorSpace::MakeSRGB();
    sk_sp<SkSurface> surface = SkSurfaces::WrapBackendRenderTarget(
        context.get(),
        backendRenderTarget,
        kTopLeft_GrSurfaceOrigin,
        kRGBA_8888_SkColorType,
        colorSpace,
        &props,
        nullptr,
        nullptr);

    if (!surface)
    {
        printf("Failed to create Skia surface.\n");
    }

    SkCanvas *canvas = surface->getCanvas();

    // Populate the return structure
    SkiaSurfaceData surfaceData;
    surfaceData.surface = surface;
    surfaceData.canvas = canvas;
    surfaceData.context = context;

    return surfaceData;
}

// Function to clear the canvas
void clearCanvas(SkCanvas *canvas, sk_sp<GrDirectContext> context, uint8_t r, uint8_t g, uint8_t b, uint8_t a)
{
    SkColor color = SkColorSetARGB(a, r, g, b);
    canvas->clear(color);
}

void drawCircle(SkCanvas *canvas, sk_sp<GrDirectContext> context, float x, float y, float width, float height, int segments, float angle_start, float angle_end)
{
    SkPaint paint;
    paint.setAntiAlias(true);
    paint.setColor(SkColorSetARGB(255, 0, 0, 255));

    // Basic circle drawing
    if (width == height && segments == 0)
    {
        float radius = width / 2.0f;
        canvas->drawCircle(x + radius, y + radius, radius, paint);
        return;
    }

    // // Draw a segmented circle or arc
    // float radius = 100.0f;
    // float centerX = x - width / 2.0f;
    // float centerY = 200.0f;
    // float angleStep = 2 * M_PI / segments;

    // SkPathBuilder builder;

    // for (int i = 0; i < segments; ++i) {
    //     float angle = i * angleStep;
    //     float cosAngle = std::cos(angle);
    //     float sinAngle = std::sin(angle);

    //     float currentX = centerX + radius * cosAngle;
    //     float currentY = centerY + radius * sinAngle;

    //     if (i == 0) {
    //         builder.moveTo({currentX, currentY});
    //     } else {
    //         builder.lineTo({currentX, currentY});
    //     }
    // }

    // builder.close();

    // paint.setStyle(SkPaint::kFill_Style);
    // paint.setStrokeWidth(3);

    // canvas->drawPath(builder.detach(), paint);
}

// Function to flush and submit the context
void flushAndSubmit(sk_sp<GrDirectContext> context)
{
    context->flushAndSubmit();
}

//////////////////////////// Lottie ////////////////////////////

sk_sp<skottie::Animation> animation;
SkRect destRect = SkRect::MakeXYWH(100, 150, 200, 200);
SkMatrix transformMatrix;
SkPaint debugPaint;

void drawLottie(SkCanvas *canvas, sk_sp<GrDirectContext> context, const char *animation_path) {
    sk_sp<SkData> data = SkData::MakeFromFileName(animation_path);
    if (!data) {
        SkDebugf("Failure loading Lottie file: %s\n", animation_path);
        return;
    }

    animation =
        skottie::Animation::Make(reinterpret_cast<const char *>(data->data()), data->size());

    if (!animation) {
        SkDebugf("Failure creating Skottie animation\n");
        return;
    }

    SkRect srcRect = SkRect::MakeSize(animation->size());

    transformMatrix = SkMatrix::RectToRect(srcRect, destRect, SkMatrix::kCenter_ScaleToFit);

    SkMatrix flip;
    flip.setScale(1, -1);
    flip.postTranslate(0, destRect.height() + destRect.y() * 2.0f);
    transformMatrix.postConcat(flip);

    debugPaint.setColor(SK_ColorBLUE);
    debugPaint.setAlpha(0x20);
    debugPaint.setStyle(SkPaint::kFill_Style);
}

void updateLottiePosAndSize(float x, float y, float width, float height) {
    SkRect srcRect = SkRect::MakeSize(animation->size());
    destRect = SkRect::MakeXYWH(x, y, width, height);

    transformMatrix = SkMatrix::RectToRect(srcRect, destRect, SkMatrix::kCenter_ScaleToFit);

    SkMatrix flip;
    flip.setScale(1, -1);
    flip.postTranslate(0, destRect.height() + destRect.y() * 2.0f);
    transformMatrix.postConcat(flip);
}

void drawLottieNextFrame(SkCanvas *canvas, sk_sp<GrDirectContext> context, float t) {
    animation->seek(t);

    canvas->save();
    canvas->resetMatrix();
    canvas->drawRect(destRect, debugPaint);

    debugPaint.setColor(SK_ColorRED);
    debugPaint.setStyle(SkPaint::kStroke_Style);
    debugPaint.setStrokeWidth(2.0f);
    canvas->drawRect(destRect, debugPaint);
    canvas->restore();

    canvas->save();
    canvas->concat(transformMatrix);
    animation->render(canvas);
    canvas->restore();
}
