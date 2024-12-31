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


class UI(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.surface = SkiaSurface(*map(int, Window.size))

        def _reset_surface(_):
            width, height = map(int, Window.size)
            self.surface = SkiaSurface(width, height)
            print(f"Surface updated - new size: {width}x{height}")

        Window.bind(on_draw=_reset_surface)

        self.surface.clear_canvas(100, 0, 0, 255)

        def clear_canvas_with_color(_):
            r = random.randint(0, 255)
            g = random.randint(0, 255)
            b = random.randint(0, 255)

            self.surface.clear_canvas(r, g, b, 255)
            self.surface.draw_circle(
                random.randint(0, 500),  # x
                random.randint(0, 500),  # y
                200,  # width
                200,  # height
                0,  # segments
                0,  # angle_start
                360,  # angle_end
            )  # basic circle

            self.surface.context_flush_and_submit()
            Window.flip()

        Clock.schedule_interval(clear_canvas_with_color, 1 / 60)


class MyApp(App):
    def build(self):
        return UI()


if __name__ == "__main__":
    MyApp().run()
