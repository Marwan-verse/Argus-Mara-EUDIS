"""Worker threads never run a Tk release; the main thread still does (no window needed)."""
import threading
import tkinter
import tkinter.font
import unittest

from PIL import ImageTk

import desktop_tk_safety


class TkReleaseGuardTests(unittest.TestCase):
    def test_release_runs_on_the_main_thread_only(self):
        released = []

        class Resource:
            def __del__(self):
                released.append(threading.current_thread().name)

        desktop_tk_safety._guard(Resource)
        desktop_tk_safety._guard(Resource)  # Installing twice keeps one guard
        Resource()
        worker = threading.Thread(target=Resource, name='worker')
        worker.start()
        worker.join()
        self.assertEqual(released, [threading.main_thread().name])

    def test_tk_fonts_images_variables_and_photos_are_guarded(self):
        desktop_tk_safety.guard_tk_finalizers()
        for cls in (tkinter.font.Font, tkinter.Image, tkinter.Variable, ImageTk.PhotoImage):
            self.assertTrue(getattr(cls.__del__, 'argus_main_thread_only', False), cls)


if __name__ == '__main__':
    unittest.main()
