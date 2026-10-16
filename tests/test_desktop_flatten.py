"""The moving picture reproduces the canvas: shapes, dashes, text, tiles, and nothing hidden or excluded."""
import gc
import tkinter as tk
import unittest

from PIL import Image

from desktop_flatten import Flattener

BACKGROUND = (3, 8, 13)


def close(colour, expected, tolerance=40):
    return all(abs(a - b) <= tolerance for a, b in zip(colour, expected))


class FlattenTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        gc.collect()  # Earlier tests' Tk objects, on the main thread
        try:
            self.root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.attributes('-alpha', 0)
        self.canvas = tk.Canvas(self.root, width=220, height=160, bg='#03080d', highlightthickness=0)
        self.canvas.pack()
        self.root.update()

    def tearDown(self):
        if hasattr(self, 'root'):
            self.root.destroy()
            gc.collect()

    def test_shapes_text_dashes_and_tiles_are_drawn_in_place(self):
        canvas = self.canvas
        tile = Image.new('RGB', (20, 20), (255, 0, 255))
        canvas.create_rectangle(10, 10, 40, 40, fill='red', outline='', tags=('chart',))
        canvas.create_line(50, 20, 150, 20, fill='#0000ff', width=3, tags=('chart',))
        canvas.create_oval(60, 60, 90, 90, fill='#00ff00', outline='', tags=('chart',))
        canvas.create_polygon(100, 60, 120, 90, 80, 90, fill='#ffff00', outline='', tags=('chart',))
        canvas.create_line(0, 140, 220, 140, fill='#ffffff', dash=(4, 4), tags=('chart',))
        text = canvas.create_text(130, 100, text='ARGUS', fill='#ffffff', anchor='nw',
                                  font=('Segoe UI', 14, 'bold'), tags=('chart',))
        canvas.create_image(150, 50, image=tk.PhotoImage(width=1, height=1), anchor='nw', tags=('chart', 'tile:1:2:3'))
        canvas.create_rectangle(180, 10, 210, 40, fill='#ff8800', outline='', state='hidden', tags=('chart',))
        canvas.create_rectangle(10, 100, 40, 130, fill='#00ffff', outline='', tags=('fixed',))
        self.root.update()

        def source(_name, tags):
            return tile if 'tile:1:2:3' in tags else None

        picture = Flattener(canvas, source).render('chart', Image.new('RGB', (220, 160), BACKGROUND))
        self.assertEqual(picture.size, (220, 160))
        self.assertTrue(close(picture.getpixel((25, 25)), (255, 0, 0)))
        self.assertTrue(close(picture.getpixel((100, 20)), (0, 0, 255)))
        self.assertTrue(close(picture.getpixel((75, 75)), (0, 255, 0)))
        self.assertTrue(close(picture.getpixel((100, 85)), (255, 255, 0)))
        self.assertTrue(close(picture.getpixel((160, 60)), (255, 0, 255)))
        self.assertTrue(close(picture.getpixel((195, 25)), BACKGROUND, 2), 'a hidden item was drawn')
        self.assertTrue(close(picture.getpixel((25, 115)), BACKGROUND, 2), 'an item outside the tag was drawn')
        dashes = [picture.getpixel((x, 140)) for x in range(0, 220)]
        lit = sum(close(colour, (255, 255, 255), 60) for colour in dashes)
        self.assertTrue(40 < lit < 180, f'dashed line drawn solid or missing: {lit} of 220 lit')
        x1, y1, x2, y2 = canvas.bbox(text)
        # Font bounds depend on Windows DPI and may extend beyond this deliberately
        # small canvas. Verify the visible text without sampling outside the image.
        inked = sum(1 for x in range(max(0, x1), min(picture.width, x2))
                    for y in range(max(0, y1), min(picture.height, y2))
                    if sum(picture.getpixel((x, y))) > 300)
        self.assertGreater(inked, 20, 'text was not drawn')
        # With an offset, canvas point (x, y) lands at (x, y) + offset: room for a ring around the view.
        shifted = Flattener(canvas, source).render('chart', Image.new('RGB', (260, 200), BACKGROUND), (20, 10))
        self.assertTrue(close(shifted.getpixel((45, 35)), (255, 0, 0)))
        self.assertTrue(close(shifted.getpixel((15, 15)), BACKGROUND, 2))


if __name__ == '__main__':
    unittest.main()
