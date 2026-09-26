import base64
from PIL import Image

def generate():
    img = Image.open('frontend/public/brand/nexus-logo-bg.png')
    bbox = img.getbbox()
    cropped = img.crop(bbox)
    w, h = cropped.size
    max_dim = max(w, h)
    margin = int(max_dim * 0.04)
    new_size = max_dim + 2 * margin
    square_img = Image.new('RGBA', (new_size, new_size), (0, 0, 0, 0))
    paste_x = (new_size - w) // 2
    paste_y = (new_size - h) // 2
    square_img.paste(cropped, (paste_x, paste_y), cropped)

    # 1. Favicon PNGs
    img16 = square_img.resize((16, 16), Image.Resampling.LANCZOS)
    img16.save('frontend/public/favicon-16.png')

    img32 = square_img.resize((32, 32), Image.Resampling.LANCZOS)
    img32.save('frontend/public/favicon-32.png')

    img48 = square_img.resize((48, 48), Image.Resampling.LANCZOS)
    img48.save('frontend/public/favicon-48.png')

    # 2. Multi-resolution favicon.ico
    img32.save('frontend/public/favicon.ico', format='ICO', sizes=[(16, 16), (32, 32), (48, 48)], append_images=[img16, img48])

    # 3. Apple Touch Icon (180x180)
    img180 = square_img.resize((180, 180), Image.Resampling.LANCZOS)
    img180.save('frontend/public/apple-touch-icon.png')

    # 4. Embedded SVG favicon (256x256)
    img256 = square_img.resize((256, 256), Image.Resampling.LANCZOS)
    img256.save('frontend/public/favicon-256.png')

    with open('frontend/public/favicon-256.png', 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')

    svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <image href="data:image/png;base64,{b64}" width="256" height="256" />
</svg>
'''
    with open('frontend/public/favicon.svg', 'w', encoding='utf-8') as f:
        f.write(svg_content)

    print("Favicons generated successfully from official canonical asset.")

if __name__ == '__main__':
    generate()
