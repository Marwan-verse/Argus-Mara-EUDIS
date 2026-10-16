"""Local outline icons and typography for the native maritime console."""
from PIL import Image, ImageDraw
import customtkinter as ctk

class Icons:
    """Original geometric icons, rendered locally at a uniform 18 px size."""
    def __init__(self):
        self.cache = {}

    def get(self, name, color='#a8b6c2', size=18):
        key = name, color, size
        if key in self.cache:
            return self.cache[key]
        scale = 4
        image = Image.new('RGBA', (24 * scale, 24 * scale))
        draw = ImageDraw.Draw(image)
        def line(points):
            draw.line([(int(x * scale), int(y * scale)) for x, y in points], fill=color, width=2 * scale, joint='curve')
        def oval(box, fill=None):
            draw.ellipse(tuple(int(v * scale) for v in box), outline=color, fill=fill, width=2 * scale)
        def rect(box):
            draw.rounded_rectangle(tuple(int(v * scale) for v in box), radius=2 * scale, outline=color, width=2 * scale)
        if name == 'alerts':
            line([(12, 3), (22, 21), (2, 21), (12, 3)])
            line([(12, 9), (12, 14)])
            oval((11, 17, 13, 19), color)
        elif name == 'ship':
            line([(5, 14), (5, 7), (10, 7), (10, 3), (14, 3), (14, 7), (19, 7), (19, 14)])
            line([(2, 14), (12, 10), (22, 14), (18, 20), (6, 20), (2, 14)])
            line([(3, 22), (7, 21), (12, 22), (17, 21), (21, 22)])
        elif name in ('views', 'home'):
            oval((3, 3, 21, 21))
            line([(15, 8), (13, 14), (8, 16), (10, 10), (15, 8)])
        elif name == 'cables':
            line([(2, 9), (6, 9), (9, 15), (13, 9), (16, 15), (20, 15), (22, 15)])
        elif name == 'ports':
            oval((9, 2, 15, 8))
            line([(12, 8), (12, 21)])
            line([(7, 11), (17, 11)])
            line([(3, 15), (4, 19), (8, 22), (12, 21), (16, 22), (20, 19), (21, 15)])
        elif name == 'radar':
            oval((3, 3, 21, 21))
            oval((7, 7, 17, 17))
            line([(12, 12), (20, 4)])
        elif name == 'magnet':  # a horseshoe magnet with solid pole tips
            line([(7, 7), (7, 12)])
            line([(17, 7), (17, 12)])
            draw.arc(tuple(int(v * scale) for v in (7, 7, 17, 17)), 0, 180, fill=color, width=2 * scale)
            for left in (5, 15):
                draw.rectangle(tuple(int(v * scale) for v in (left, 2, left + 4, 7)), fill=color)
        elif name == 'weather':
            line([(5, 19), (3, 17), (3, 13), (6, 10), (9, 10), (11, 6), (16, 6), (19, 10), (19, 12), (22, 14), (22, 17), (20, 19), (5, 19)])
        elif name == 'layers':
            line([(2, 8), (12, 3), (22, 8), (12, 13), (2, 8)])
            line([(3, 13), (12, 18), (21, 13)])
            line([(3, 18), (12, 23), (21, 18)])
        elif name == 'replay':
            oval((3, 3, 21, 21))
            line([(10, 7), (17, 12), (10, 17), (10, 7)])
        elif name == 'evidence':
            line([(5, 3), (15, 3), (20, 8), (20, 21), (5, 21), (5, 3)])
            line([(15, 3), (15, 8), (20, 8)])
            line([(9, 12), (16, 12)])
            line([(9, 16), (16, 16)])
        elif name == 'search':
            oval((3, 3, 16, 16))
            line([(15, 15), (22, 22)])
        elif name == 'pen':
            line([(4, 16), (17, 3), (21, 7), (8, 20), (3, 21), (4, 16), (8, 20)])
            line([(14, 6), (18, 10)])
        elif name == 'measure':
            rect((3, 7, 21, 17))
            for x in (7, 11, 15, 19):
                line([(x, 7), (x, 11 if x % 3 else 13)])
        elif name == 'ping':
            oval((5, 5, 19, 19))
            oval((10, 10, 14, 14), color)
            for points in (((12, 1), (12, 5)), ((12, 19), (12, 23)),
                           ((1, 12), (5, 12)), ((19, 12), (23, 12))):
                line(points)
        elif name == 'refresh':
            draw.arc(tuple(int(v * scale) for v in (4, 4, 20, 20)), 300, 230, fill=color, width=2 * scale)
            line([(3, 4), (7, 6), (9, 2)])
        elif name == 'plus':
            line([(4, 12), (20, 12)])
            line([(12, 4), (12, 20)])
        elif name == 'minus':
            line([(4, 12), (20, 12)])
        elif name == 'close':
            line([(5, 5), (19, 19)])
            line([(5, 19), (19, 5)])
        elif name == 'satellite':
            line([(8, 9), (13, 4), (19, 10), (14, 15), (8, 9)])
            line([(9, 10), (4, 15), (9, 20), (14, 15)])
            line([(4, 5), (8, 9)])
            line([(15, 18), (20, 23)])
        elif name == 'brand':
            line([(2, 12), (6, 7), (12, 5), (18, 7), (22, 12), (18, 17), (12, 19), (6, 17), (2, 12)])
            oval((8, 8, 16, 16))
        else:
            raise ValueError(f'Unknown native icon: {name}')
        image = image.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
        result = ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
        self.cache[key] = result
        return result
