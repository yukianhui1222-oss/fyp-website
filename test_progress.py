import os
from ocr_engine import extract_text_from_image
import logging

def test():
    # Create dummy image
    from PIL import Image
    img = Image.new('RGB', (100, 100), color = 'red')
    img.save('dummy.png')
    
    class DummyFile:
        def __init__(self, path):
            self.name = path
            with open(path, 'rb') as f:
                self.data = f.read()
            self.pos = 0
        def read(self):
            return self.data
        def seek(self, pos):
            pass
            
    f = DummyFile('dummy.png')
    
    print("=== First Run ===")
    extract_text_from_image(f)
    print("=== Second Run ===")
    extract_text_from_image(f)
    
if __name__ == '__main__':
    test()
