import asyncio
from playwright.async_api import async_playwright
import os
import base64
from urllib.parse import urlparse, urljoin, unquote
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
        page_save_path (str): Path where the webpage and assets will be saved.
    """
    logger.info(f"Saving page: {url}")

    # Ensure save path exists
    if not os.path.exists(page_save_path):
        os.makedirs(page_save_path)

    error_log_path = os.path.join(page_save_path, 'errors.md')
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(url, wait_until='networkidle')
            logger.info(f"Page loaded: {url}")

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
                    if asset_url.startswith('data:'):
                        # Handle data URLs
                        mime_type, data = asset_url.split(',', 1)
                        file_extension = mime_type.split(';')[0].split('/')[1]
                        file_name = f"inline_asset_{hash(data)}.{file_extension}"
                        file_path = os.path.join(assets_dir, file_name)
                        
                        if 'base64' in mime_type:
                            data = base64.b64decode(data)
                        else:
                            data = unquote(data).encode('utf-8')
                        
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(data)
                    else:
                        # Handle regular URLs
                        asset_url = urljoin(url, asset_url)  # Handle relative URLs
                        response = await page.goto(asset_url)
                        if response:
                            buffer = await response.body()
                            parsed_url = urlparse(asset_url)
                            file_name = os.path.basename(parsed_url.path) or f"asset_{hash(asset_url)}"
                            file_path = os.path.join(assets_dir, file_name)

                            async with aiofiles.open(file_path, 'wb') as f:
                                await f.write(buffer)
                        else:
                            raise Exception(f"Failed to fetch asset: {asset_url}")

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
        system_message = "You are a website copy translator. Provide only the translation. Do not ask for clarity or offer suggestions. If a word doesn't appear to have a translation leave it as is."
        
        if content_type:
            system_message += f" You are currently translating {content_type} content."

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"Translate the following text to Spanish: {text}"}
        ]
        response = await openai_helper.send_message_async(messages)
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
                translated_content = await send_text_to_openai(original_content, content_type="meta tag")
                meta['content'] = translated_content

        # Translate img alt attributes
        for img in soup.find_all('img', alt=True):
            original_alt = img['alt']
            if original_alt.strip():
                translated_alt = await send_text_to_openai(original_alt, content_type="image alt text")
                img['alt'] = translated_alt

        # Translate visible text content
        for element in soup.find_all(text=True):
            if element.parent.name not in ['script', 'style', 'head', 'meta', '[document]']:
                if element.string and element.string.strip():
                    content_type = f"{element.parent.name} element"
                    translated_text = await send_text_to_openai(element.string, content_type=content_type)
                    element.string.replace_with(translated_text)

        return str(soup)
    except Exception as e:
        logger.error(f"Error translating HTML content: {e}")
        return html_content

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
url = 'https://www.example.com'
page_save_path = save_dir_info(url)

html_content = asyncio.run(save_page_with_assets(url, page_save_path))

asyncio.run(translate_page(html_content, page_save_path))