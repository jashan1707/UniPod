from pdf2image import convert_from_bytes
import pytesseract

def extract_text_from_pdf(file):
    images = convert_from_bytes(file.read())
    text = ""
    for img in images:
        text += pytesseract.image_to_string(img)
    return text
