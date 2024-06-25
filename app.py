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

async def save_page_with_assets(url: str, base_save_path: str):
    """
    Save a webpage along with its assets.

    Args:
        url (str): URL of the webpage to save.
        base_save_path (str): Base path where the webpage directory will be created.
    """
    logger.info(f"Saving page: {url}")
    
    # Create directory name from URL
    dir_name = url_to_dirname(url)
    save_path = os.path.join(base_save_path, dir_name)
    
    # Ensure save path exists
    if not os.path.exists(save_path):
        os.makedirs(save_path)

    error_log_path = os.path.join(save_path, 'errors.md')
    
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

            assets_dir = os.path.join(save_path, 'assets')
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
            html_file_path = os.path.join(save_path, 'webpage.html')
            async with aiofiles.open(html_file_path, 'w', encoding='utf-8') as f:
                await f.write(html_content)
            logger.info(f"HTML content saved: {html_file_path}")

            # Translate HTML content
            translated_html_content = await translate_html_content(html_content)
            translated_html_file_path = os.path.join(save_path, 'webpage_translated.html')
            async with aiofiles.open(translated_html_file_path, 'w', encoding='utf-8') as f:
                await f.write(translated_html_content)
            logger.info(f"Translated HTML content saved: {translated_html_file_path}")

        except Exception as e:
            error_message = f"Failed to save page {url}: {e}\n"
            async with aiofiles.open(error_log_path, 'a', encoding='utf-8') as f:
                await f.write(error_message)
            logger.error(error_message)
        finally:
            # Close the browser
            await browser.close()

async def translate_html_content(html_content: str) -> str:
    """
    Translate the text content of the HTML to Spanish.

    Args:
        html_content (str): The HTML content to translate.

    Returns:
        str: The translated HTML content.
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        text_nodes = []

        # Extract all text nodes
        for element in soup.find_all(text=True):
            if element.parent.name not in ['script', 'style', 'head', 'title', 'meta', '[document]']:
                text_nodes.append(element)

        # Translate text nodes
        for node in text_nodes:
            original_text = node.string
            if original_text.strip():
                translated_text = await send_text_to_openai(original_text)
                node.string.replace_with(translated_text)

        return str(soup)
    except Exception as e:
        logger.error(f"Error translating HTML content: {e}")
        return html_content

async def send_text_to_openai(text: str) -> str:
    """
    Send the text content to OpenAI for processing.

    Args:
        text (str): The text content to send.

    Returns:
        str: The response from OpenAI.
    """
    try:
        messages = [
            {"role": "system", "content": "You are a translator."},
            {"role": "user", "content": f"Translate the following text to Spanish: {text}"}
        ]
        response = await openai_helper.send_message_async(messages)
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error sending text to OpenAI: {e}")
        return str(e)

# Add the downloads directory using AppPaths
AppPaths.add("_downloaded_pages")

# Example usage
url = 'https://offhourscreative.com'
save_path = AppPaths._DOWNLOADED_PAGES_DIR
asyncio.run(save_page_with_assets(url, save_path))
