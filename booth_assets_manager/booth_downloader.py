import os
import re
import json
import asyncio
import urllib.parse
from datetime import datetime
from tqdm import tqdm
from playwright.async_api import async_playwright
from .settings import settings

LIBRARY_URL = "https://accounts.booth.pm/library"

# Extraction script for one page of https://accounts.booth.pm/library.
# Booth renders each purchased item as a card with a thumbnail link and one or
# more ".js-download-button" elements carrying the real download URL.
EXTRACT_LIBRARY_JS = """
() => {
  const items = [];
  const seen = new Set();
  document.querySelectorAll('img.l-library-item-thumbnail').forEach(img => {
    const link = img.closest('a');
    if (!link) return;
    const match = link.href.match(/\\/(?:[a-z]{2}\\/)?items\\/(\\d+)/);
    if (!match) return;
    const itemId = match[1];
    if (seen.has(itemId)) return;
    seen.add(itemId);

    const card = link.closest('div.bg-white') || link.parentElement.parentElement;
    const titleEl = card.querySelector('.text-16.font-bold') || card.querySelector('.text-16');

    const files = [...card.querySelectorAll('.js-download-button')].map(btn => {
      const row = btn.closest('div.mt-16');
      const nameEl = row ? row.querySelector('div.text-14') : null;
      return {
        filename: nameEl ? nameEl.innerText.trim() : (btn.dataset.label || 'download'),
        url: btn.dataset.href || '',
        external: btn.dataset.isExternal === 'true'
      };
    }).filter(f => f.url);

    items.push({
      item_id: itemId,
      title: titleEl ? titleEl.innerText.trim() : '',
      url: `https://booth.pm/ja/items/${itemId}`,
      files: files
    });
  });
  return items;
}
"""

# Library entries cached per process, filled by get_purchased_items().
_library_cache = {}


class BoothDownloader:
    """
    Handles downloading files from Booth using browser automation.
    """

    def __init__(self):
        self.cookies_path = settings.get("auth_cookies_file")
        if not self.cookies_path:
            self.cookies_path = os.path.join(
                os.path.dirname(settings.config_path), "booth_cookies.json"
            )
        self.download_base_dir = settings.get("download_directory") or "BoothDownloads"
        os.makedirs(self.download_base_dir, exist_ok=True)

    def sanitize_filename(self, filename):
        """Sanitize a string to be used as a safe filename."""
        filename = os.path.basename(filename).strip() or "download"
        return re.sub(r'[\\/*?:"<>|]', "", filename.replace(" ", "_"))

    def _load_cookies(self):
        if not self.cookies_path or not os.path.exists(self.cookies_path):
            raise Exception("Not authenticated. Please login first.")
        with open(self.cookies_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    async def _new_page(self, browser, accept_downloads=False):
        context = await browser.new_context(accept_downloads=accept_downloads)
        await context.add_cookies(self._load_cookies())
        page = await context.new_page()
        return context, page

    async def _scan_library(self, page, start_page=1, max_pages=60):
        """
        Walk the BOOTH library and return every purchased item with its files.
        The library is paginated server side (?page=N).
        """
        items = []
        seen_ids = set()

        for page_number in range(start_page, start_page + max_pages):
            url = f"{LIBRARY_URL}?page={page_number}"
            await page.goto(url, wait_until="domcontentloaded")

            if '/users/sign_in' in page.url:
                raise Exception("Session expired. Please login again.")

            try:
                await page.wait_for_selector('.l-library-item-thumbnail, .l-library-empty', timeout=15000)
            except Exception:
                # Nothing rendered: stop rather than loop forever.
                break

            page_items = await page.evaluate(EXTRACT_LIBRARY_JS)
            new_items = [item for item in page_items if item['item_id'] not in seen_ids]
            for item in new_items:
                seen_ids.add(item['item_id'])
            items.extend(new_items)

            # Stop at the last page (no next link) or when nothing new shows up.
            if not new_items:
                break
            has_next = await page.locator("a[rel='next']").count() > 0
            if not has_next:
                break
            await asyncio.sleep(0.3)

        return items

    async def get_purchased_items(self):
        """
        Fetch list of purchased items from the BOOTH library.
        Returns a list of dictionaries with item details.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context, page = await self._new_page(browser)
                items = await self._scan_library(page)
            finally:
                await browser.close()

        for item in items:
            _library_cache[item['item_id']] = item
            # Purchase date / price are not exposed on the library listing.
            item['purchase_date'] = None
            item['price'] = None
            item['files'] = item.get('files', [])

        return items

    async def get_download_links(self, item_id):
        """
        Get download links for a purchased item.
        Returns a list of dictionaries with file details.
        """
        if item_id in _library_cache:
            files = _library_cache[item_id]['files']
        else:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    context, page = await self._new_page(browser)
                    items = await self._scan_library(page)
                finally:
                    await browser.close()

            items = await self._cached_or_items(items)
            match = next((i for i in items if i['item_id'] == item_id), None)
            if not match:
                raise Exception(f"Item {item_id} was not found in your BOOTH library.")
            files = match['files']

        return [
            {
                'filename': f['filename'],
                'size': None,
                'url': f['url'],
                'external': f.get('external', False),
            }
            for f in files
        ]

    async def _cached_or_items(self, items):
        for item in items:
            _library_cache[item['item_id']] = item
        return items

    async def download_file(self, download_url, item_id, item_title, filename):
        """
        Download a file using browser automation.
        Returns the path to the downloaded file.
        """
        safe_title = self.sanitize_filename(item_title)
        item_folder = os.path.join(self.download_base_dir, f"{item_id}_{safe_title}")
        downloads_folder = os.path.join(item_folder, "downloads")
        os.makedirs(downloads_folder, exist_ok=True)

        file_path = os.path.join(downloads_folder, self.sanitize_filename(filename))

        # Skip if file already exists and is not empty
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            print(f"File already exists: {file_path}")
            return file_path

        print(f"Downloading {filename} to {file_path}...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context, page = await self._new_page(browser, accept_downloads=True)
                context.set_default_timeout(120000)

                async with page.expect_download(timeout=120000) as download_info:
                    try:
                        await page.goto(download_url, wait_until='domcontentloaded')
                    except Exception as e:
                        # A navigation interruption is expected when the response
                        # is a file download rather than a page.
                        if 'net::ERR_ABORTED' not in str(e) and 'Download is starting' not in str(e):
                            raise

                if '/users/sign_in' in page.url:
                    raise Exception("Session expired. Please login again.")

                download = await download_info.value

                progress_bar = tqdm(total=100, desc=f"Downloading {filename}", unit="%")
                await download.save_as(file_path)
                progress_bar.update(100 - progress_bar.n)
                progress_bar.close()

                print(f"Download complete: {file_path}")
                return file_path
            except Exception as e:
                print(f"Error downloading file: {e}")
                return None
            finally:
                await browser.close()


# Helper functions to run async methods
def get_purchased_items():
    """Get list of purchased items."""
    downloader = BoothDownloader()
    return asyncio.run(downloader.get_purchased_items())

def get_download_links(item_id):
    """Get download links for an item."""
    downloader = BoothDownloader()
    return asyncio.run(downloader.get_download_links(item_id))

def download_file(download_url, item_id, item_title, filename):
    """Download a file."""
    downloader = BoothDownloader()
    return asyncio.run(downloader.download_file(download_url, item_id, item_title, filename))

# Advanced functionality for parallel downloads
async def download_multiple_files(item_id, item_title, download_links, max_concurrent=3):
    """Download multiple files concurrently with limited concurrency."""
    downloader = BoothDownloader()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def download_with_limit(link):
        async with semaphore:  # Limit concurrent downloads
            result = await downloader.download_file(
                link['url'],
                item_id,
                item_title,
                link['filename']
            )
            return {
                'filename': link['filename'],
                'path': result,
                'success': result is not None
            }

    # Create download tasks
    tasks = [download_with_limit(link) for link in download_links]

    # Execute all tasks concurrently
    results = await asyncio.gather(*tasks)

    return results

def download_all_files(item_id, item_title, max_concurrent=3):
    """Download all files for an item with concurrency control."""
    try:
        # Get download links
        links = get_download_links(item_id)

        if not links:
            print(f"No download links found for item {item_id}")
            return []

        external = [link for link in links if link.get('external')]
        links = [link for link in links if not link.get('external')]
        for link in external:
            print(f"Skipping external download (open in browser): {link['filename']} -> {link['url']}")

        if not links:
            print(f"No direct download links found for item {item_id}")
            return []

        # Download all files concurrently
        results = asyncio.run(download_multiple_files(
            item_id,
            item_title,
            links,
            max_concurrent
        ))

        # Print summary
        successful = [r for r in results if r['success']]
        print(f"\nDownload summary for {item_title}:")
        print(f"  Total files: {len(results)}")
        print(f"  Successfully downloaded: {len(successful)}")
        print(f"  Failed: {len(results) - len(successful)}")

        return results

    except Exception as e:
        print(f"Error downloading files for item {item_id}: {e}")
        return []
