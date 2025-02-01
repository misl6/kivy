import os
# os.environ["KIVY_GL_BACKEND"] = "angle_sdl2"

import random

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import ListProperty, ObjectProperty
from kivy.uix.floatlayout import FloatLayout

from kivy.core.skia.pure_skia import SkiaSurface

Window.clear = lambda: None


def _reset_skia_surface(_):
    width, height = map(int, Window.size)
    Window.skia_surface = SkiaSurface(width, height)
    print(f"Surface updated - new size: {width}x{height}")


Window.bind(on_draw=_reset_skia_surface)
Window.skia_surface = SkiaSurface(*map(int, Window.size))


class UI(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        Window.skia_surface.draw_lottie("confetti.json")
        # Window.skia_surface.draw_lottie("lego_loader.json")
        # Window.skia_surface.draw_lottie("anim_1.json")
        # Window.skia_surface.draw_lottie("anim_2.json")
        # Window.skia_surface.draw_lottie("anim_3.json")

        def _update_lottie_pos_size(dt):
            Window.skia_surface.update_lottie_pos_and_size(
                random.randint(0, 300),
                random.randint(0, 300),
                *[random.randint(100, 500)] * 2,
            )

        Clock.schedule_interval(_update_lottie_pos_size, 1)

        t = 0

        def _update_lottie_anim(dt):
            nonlocal t
            t += (
                1 / 300
            )  # 300 is hardcoded; the higher the value, the slower the animation

            Window.skia_surface.clear_canvas(0, 0, 100, 255)
            Window.skia_surface.lottie_seek(t)
            Window.skia_surface.context_flush_and_submit()
            Window.flip()

            if t >= 1:
                t = 0

        Clock.schedule_interval(_update_lottie_anim, 1 / 60)


class MyApp(App):
    def build(self):
        return UI()


if __name__ == "__main__":
    MyApp().run()
