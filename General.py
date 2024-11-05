import os
import cv2
import numpy as np
from moviepy.editor import VideoFileClip
from fpdf import FPDF
import pysrt
from bs4 import BeautifulSoup
import requests
import json
from PIL import Image
from io import BytesIO
import zipfile
import re
import tempfile
import io

# Function to extract movie name
def movie_name(filepath):
    parts_to_remove = [
        "1080P", "720P", "480P", "Bluray", "Webrip", "HDrip", "DVDrip",
        "Softsub", "Digimoviez", "BRRip", "YIFY"
    ]
    filename = os.path.basename(filepath)
    if '.' in filename:
        filename = filename.rsplit('.', 1)[0]
    parts = filename.split('.')
    title_parts = []
    for part in parts:
        if part.isdigit() and len(part) == 4:
            continue
        if part in parts_to_remove:
            continue
        title_parts.append(part)
    title = ' '.join(title_parts)
    return title

# Function to extract screenshots from a video file
def extract_screenshots(input_file, interval, output_dir):
    screenshot_folder = os.path.join(output_dir, "Screenshots")
    if not os.path.exists(screenshot_folder):
        os.makedirs(screenshot_folder)
    try:
        clip = VideoFileClip(input_file)
        for t in np.arange(0, clip.duration, interval):
            frame = clip.get_frame(t)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            screenshot_path = os.path.join(screenshot_folder, f'screenshot-{int(t):03d}.jpg')
            cv2.imwrite(screenshot_path, frame_rgb)
            print(f'Screenshot saved: {screenshot_path}')
        clip.close()
        print(f"Screenshots saved in directory: {screenshot_folder}")
    except Exception as e:
        print(f"Error extracting screenshots: {e}")
    return screenshot_folder

# Function to convert time to seconds for subtitles
def time_to_seconds(t):
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1_000_000

# Function to sanitize subtitle text
def sanitize_text(text):
    return ''.join(c for c in text if ord(c) < 256)  # Keep only characters in Latin-1 range

# Function to create a PDF with combined content
def create_pdf(input_file, screenshot_folder, srt_file, full_cast_crew, tolerance=2.5):
    # Parse SRT file
    subs = pysrt.open(srt_file)
    subtitle_dict = {}

    for sub in subs:
        start_time = sub.start.to_time()
        end_time = sub.end.to_time()
        subtitle_text = sanitize_text(BeautifulSoup(sub.text, "html.parser").get_text())
        subtitle_dict[(time_to_seconds(start_time), time_to_seconds(end_time))] = subtitle_text

    # Get screenshot files
    screenshots = [f for f in os.listdir(screenshot_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    screenshots.sort()  # Assuming filenames are sortable for chronological order

    # Track used subtitles
    used_subtitles = set()

    # Create PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Add title to PDF
    base_name = os.path.splitext(os.path.basename(input_file))[0].split('.')[0]
    pdf.set_font('Arial', 'B', 24)
    pdf.cell(0, 10, txt=base_name, ln=True, align='C')
    pdf.ln(10)

    # Add cast and crew information
    pdf.set_font('Arial', 'B', 20)
    pdf.cell(0, 10, txt="Cast and Crew", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=10)

    x_start = 40
    y_start = 40
    line_height = 15  # Adjust based on content and image size
    text_width = 80
    max_casts_per_page = 16  # Number of casts per page

    current_y = y_start

    def resize_image(image_bytes, width, height, quality=100):
        img = Image.open(BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        img = img.resize((width, height), Image.LANCZOS)
        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=quality, optimize=True)
        img_byte_arr.seek(0)
        return img_byte_arr

    for index, (name, details) in enumerate(full_cast_crew.items()):
        character = details.get('character', 'N/A')
        image_url = details.get('image_url', None)

        if index > 0 and index % max_casts_per_page == 0:
            pdf.add_page()
            pdf.set_font("Arial", size=10)
            current_y = 10

        pdf.set_xy(x_start, current_y)
        pdf.set_font("Arial", 'B', size=8)
        pdf.cell(text_width, line_height, txt=f"Name: {name}", ln=False)
        pdf.set_font("Arial", size=8)
        pdf.cell(text_width, line_height, txt=f"Character: {character}", ln=False)

        if image_url:
            try:
                response = requests.get(image_url)
                img_byte_arr = resize_image(response.content, 350, 400)

                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                    temp_file.write(img_byte_arr.getvalue())
                    temp_file_path = temp_file.name

                pdf.image(temp_file_path, x=x_start - 25, y=current_y + 2, w=8)
                os.remove(temp_file_path)

            except Exception as e:
                print(f"Failed to load image: {e}")
        current_y += line_height  # Move down for the next entry

    pdf.set_font('Arial', '', 12)

    for i in range(0, len(screenshots), 2):
        pdf.add_page()
        screenshot_path = os.path.join(screenshot_folder, screenshots[i])
        screenshot_time_str = screenshots[i].split('-')[1].split('.')[0]
        screenshot_time = int(screenshot_time_str)

        matching_texts = []
        for (start_time, end_time), text in subtitle_dict.items():
            if start_time <= screenshot_time + tolerance and end_time >= screenshot_time - tolerance:
                if (start_time, end_time) not in used_subtitles:
                    matching_texts.append(text)
                    used_subtitles.add((start_time, end_time))

        subtitle_text = '\n'.join(matching_texts)

        pdf.image(os.path.join(screenshot_folder, screenshots[i]), x=10, y=20, w=pdf.w - 20)
        pdf.ln(140)  # Adjust this value based on image height

        pdf.multi_cell(0, 8, subtitle_text)

        if i + 1 < len(screenshots):
            screenshot_time_str = screenshots[i + 1].split('-')[1].split('.')[0]
            screenshot_time = int(screenshot_time_str)

            matching_texts = []
            for (start_time, end_time), text in subtitle_dict.items():
                if start_time <= screenshot_time + tolerance and end_time >= screenshot_time - tolerance:
                    if (start_time, end_time) not in used_subtitles:
                        matching_texts.append(text)
                        used_subtitles.add((start_time, end_time))

            subtitle_text = '\n'.join(matching_texts)

            pdf.image(os.path.join(screenshot_folder, screenshots[i + 1]), x=10, y=160, w=pdf.w - 20)
            pdf.ln(140)  # Adjust this value based on image height

            pdf.multi_cell(0, 8, subtitle_text)

    pdf_output_path = os.path.join(screenshot_folder, 'Final.pdf')
    pdf.output(pdf_output_path)
    print(f'PDF created at {pdf_output_path}')

# Function to get movie info from IMDb
def get_movie_info(movie_title):
    start_url = f"https://www.imdb.com/find?q={movie_title}"
    header = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36"}

    response = requests.get(start_url, headers=header)
    soup = BeautifulSoup(response.content, 'html.parser')
    url = []
    for link in soup.find_all('a', class_='ipc-metadata-list-summary-item__t'):
        if link.has_attr('href'):
            url.append(link)

    if not url:
        print("No movie found on IMDb.")
        return {}

    movie_url = 'https://www.imdb.com/' + url[0]['href']
    response = requests.get(movie_url, headers=header)
    soup = BeautifulSoup(response.content, 'html.parser')

    urls = []
    for link in soup.find_all('a'):
        if link.has_attr('href') and 'fullcredits' in link['href']:
            urls.append(f"https://www.imdb.com{link['href']}")

    if not urls:
        print("No full credits found on IMDb.")
        return {}

    cast_url = urls[0]
    response = requests.get(cast_url, headers=header)
    soup = BeautifulSoup(response.content, 'html.parser')

    cast_list = []
    char_list = []
    img_urls = []

    cast_table = soup.find('table', class_='cast_list')
    if cast_table:
        for row in cast_table.find_all('tr'):
            img_tag = row.find('img')
            if img_tag:
                img_url = img_tag.get('data-src') or img_tag.get('loadlate') or img_tag.get('src')
                img_urls.append(img_url)

    for row in cast_table.find_all('tr'):
        columns = row.find_all('td')
        if len(columns) > 1:
            cast_list.append(columns[1].text.strip())
        if len(columns) > 3:
            char_list.append(columns[3].text.strip())

    full_cast_crew = {}
    for actor, character, img_url in zip(cast_list, char_list, img_urls):
        full_cast_crew[actor] = {
            'character': character,
            'image_url': img_url
        }

    with open('full_cast_crew.json', 'w') as f:
        json.dump(full_cast_crew, f, indent=4)

    print("Cast information has been saved.")
    return full_cast_crew

# Function to extract movie info from filename
def extract_movie_info(filename):
    pattern = re.compile(
        r'^(?P<name>.+?)\.(?P<year>\d{4})\.(?P<quality>\d{3,4}P)\.(?P<type>[A-Za-z0-9]+)(?:\.(?P<subtype>.+))?$',
        re.IGNORECASE
    )
    match = pattern.match(filename)
    if match:
        name = match.group('name').replace('.', ' ')
        year = match.group('year')
        quality = match.group('quality')
        type_ = match.group('type')
        subtype = match.group('subtype') if match.group('subtype') else 'N/A'
        return {
            'name': name,
            'year': year,
            'quality': quality,
            'type': type_,
            'subtype': subtype
        }
    else:
        return None

# Function to extract subtitles
def extract_subtitle(movie_info, movie_dir):
    movie_name = movie_info['name']
    type_ = movie_info['type'].lower()
    quality = movie_info['quality'].lower()
    formatted_movie_name = movie_name.replace(" ", "-")
    url = requests.get(f'https://subdl.com/search?query={formatted_movie_name}')
    url_soup = BeautifulSoup(url.content, 'html.parser')
    urls = []
    for link in url_soup.find_all('a', href=True):
        href = link['href']
        if '/subtitle/' in href:
            urls.append(href)
    urls = list(dict.fromkeys(urls))
    if not urls:
        print("No subtitles found for this movie.")
        return None
    sub_link = 'https://subdl.com' + urls[0] + '/english'
    subtitles_url = requests.get(sub_link)
    subtitles_soup = BeautifulSoup(subtitles_url.content, 'html.parser')
    links = []
    subtitle_links = subtitles_soup.select('a[href^="https://dl.subdl.com/subtitle/"]')
    for link in subtitle_links:
        if 'info' not in link['href'] and 'ubitle/sd' not in link['href']:
            text = link.text.lower().strip().replace('-','')
            if type_ and quality in text:
                links.append(link['href'])
    if not links:
        print("No matching subtitles found.")
        return None
    download_link = links[0]
    r = requests.get(download_link)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        extract_path = movie_dir
        os.makedirs(extract_path, exist_ok=True)
        z.extractall(extract_path)
        print(f'The subtitle saved in {extract_path}.')
        srt_files = [f for f in os.listdir(extract_path) if f.endswith('.srt')]
        if srt_files:
            return os.path.join(extract_path, srt_files[0])
        else:
            return None

if __name__ == "__main__":
    input_file = input("Please drop the video file into the terminal and press Enter:").strip()
    
    while True:
        if os.path.isfile(input_file):
            movie_dir = os.path.dirname(input_file)
            interval_num = int(input('Enter intervals (in seconds): '))
            screenshot_folder = extract_screenshots(input_file, interval=interval_num, output_dir=movie_dir)
            
            movie_info = extract_movie_info(os.path.basename(input_file))
            if movie_info:
                srt_file = extract_subtitle(movie_info, movie_dir)
                if srt_file and os.path.isfile(srt_file):
                    movie_title = movie_info['name']
                    full_cast_crew = get_movie_info(movie_title)
                    if full_cast_crew:
                        create_pdf(input_file, screenshot_folder, srt_file, full_cast_crew, tolerance=interval_num / 2)
                    break
                else:
                    print("Failed to extract or find the subtitle file.")
            else:
                print("Failed to extract movie information from the filename.")
        else:
            print("Invalid video file path. Please drop the video file into the terminal and press Enter again:")
            input_file = input().strip()
