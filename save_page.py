import asyncio
from playwright.async_api import async_playwright
import os
from urllib.parse import urlparse, urljoin
import aiofiles
from tkr_utils.app_paths import AppPaths  # Import AppPaths
from tkr_utils.helper_openai import OpenAIHelper  # Import OpenAIHelper
import logging
from bs4 import BeautifulSoup  # Import BeautifulSoup for HTML parsing

# Setup logging for this module
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize OpenAIHelper once
openai_helper = OpenAIHelper(async_mode=True)

def url_to_dirname(url: str) -> str:
    """Convert a URL to a valid directory name.

    Args:
        url (str): The URL to convert.

    Returns:
        str: The converted directory name.
    """
    parsed_url = urlparse(url)
    return parsed_url.netloc.replace('www.', '').replace('.', '_')


async def save_page_with_assets(url: str, page_save_path):
    """
    Save a webpage along with its assets.

    Args:
        url (str): URL of the webpage to save.
        base_save_path (str): Base path where the webpage directory will be created.
    """
    logger.info(f"Saving page: {url}")

    # Ensure save path exists
    if not os.path.exists(page_save_path):
        os.makedirs(page_save_path)

    error_log_path = os.path.join(page_save_path, 'errors.md')
    
    async with async_playwright() as p:
        # Launch the browser
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Navigate to the webpage
            await page.goto(url, wait_until='networkidle')
            logger.info(f"Page loaded: {url}")

            # Save the HTML content
            html_content = await page.content()

            # Extract and save all assets
            urls = await page.evaluate('''() => {
                const links = Array.from(document.querySelectorAll('link[rel="stylesheet"], script[src], img[src]'));
                return links.map(link => link.href || link.src);
            }''')

            assets_dir = os.path.join(page_save_path, 'assets')
            if not os.path.exists(assets_dir):
                os.makedirs(assets_dir)

            for asset_url in urls:
                try:
                    asset_url = urljoin(url, asset_url)  # Handle relative URLs
                    response = await page.goto(asset_url)
                    buffer = await response.body()
                    parsed_url = urlparse(asset_url)
                    file_name = os.path.basename(parsed_url.path)

                    file_path = os.path.join(assets_dir, file_name)

                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(buffer)

                    # Update HTML content to reference local asset files
                    html_content = html_content.replace(asset_url, f'assets/{file_name}')
                except Exception as e:
                    error_message = f"Failed to download {asset_url}: {e}\n"
                    async with aiofiles.open(error_log_path, 'a', encoding='utf-8') as f:
                        await f.write(error_message)
                    logger.error(error_message)

            # Save the modified HTML content
            html_file_path = os.path.join(page_save_path, 'webpage.html')
            async with aiofiles.open(html_file_path, 'w', encoding='utf-8') as f:
                await f.write(html_content)
            logger.info(f"HTML content saved: {html_file_path}")

        except Exception as e:
            error_message = f"Failed to save page {url}: {e}\n"
            async with aiofiles.open(error_log_path, 'a', encoding='utf-8') as f:
                await f.write(error_message)
            logger.error(error_message)
        finally:
            # Close the browser
            await browser.close()

        return html_content
    

async def send_text_to_openai(text: str, content_type: str = None) -> str:
    """
    Send the text content to OpenAI for processing.

    Args:
        text (str): The text content to send.
        content_type (str, optional): The type of content being translated.

    Returns:
        str: The response from OpenAI.
    """
    try:
        messages = [
            {"role": "system", "content": "You are a website copy translator. Provide only the translation. Do not ask for clarity or offer suggestions. If a word doesn't appear to have a translation leave it as is."},
            {"role": "user", "content": f"Translate the following text to Spanish: {text}"}
        ]
        response = await openai_helper.send_message_async(messages, content_type=content_type)
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error sending text to OpenAI: {e}")
        return str(e)

async def translate_html_content(html_content: str) -> str:
    """
    Translate the text content of the HTML to Spanish, including meta tags and img alt attributes.

    Args:
        html_content (str): The HTML content to translate.

    Returns:
        str: The translated HTML content.
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Translate meta tags
        for meta in soup.find_all('meta', attrs={'name': ['description', 'keywords']}):
            if 'content' in meta.attrs:
                original_content = meta['content']
                translated_content = await send_text_to_openai(original_content, content_type="meta")
                meta['content'] = translated_content

        # Translate img alt attributes
        for img in soup.find_all('img', alt=True):
            original_alt = img['alt']
            if original_alt.strip():
                translated_alt = await send_text_to_openai(original_alt, content_type="img")
                img['alt'] = translated_alt

        # Translate visible text content
        for element in soup.find_all(text=True):
            if element.parent.name not in ['script', 'style', 'head', 'meta', '[document]']:
                if element.string and element.string.strip():
                    translated_text = await send_text_to_openai(element.string, content_type="element")
                    element.string.replace_with(translated_text)

        return str(soup)
    except Exception as e:
        logger.error(f"Error translating HTML content: {e}")
        return html_content

async def translate_page(html_content, site_save_path):
    translated_html_content = await translate_html_content(html_content)
    translated_html_file_path = os.path.join(site_save_path, 'webpage_translated.html')
    async with aiofiles.open(translated_html_file_path, 'w', encoding='utf-8') as f:
        await f.write(translated_html_content)
    logger.info(f"Translated HTML content saved: {translated_html_file_path}")

def save_dir_info(url):
    dir_name = url_to_dirname(url)
    page_save_path = AppPaths._DOWNLOADED_PAGES_DIR / dir_name
    return page_save_path
    

# Add the downloads directory using AppPaths
AppPaths.add("_downloaded_pages")

# Example usage
url = 'https://futuretools.io'
page_save_path = save_dir_info(url)

html_content = asyncio.run(save_page_with_assets(url, page_save_path))

asyncio.run(translate_page(html_content, page_save_path))