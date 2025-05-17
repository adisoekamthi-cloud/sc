import requests
import re
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
import nest_asyncio

# Mengizinkan nested event loop di environment seperti Jupyter
nest_asyncio.apply()

def convert_pixeldrain_url(url):
    match = re.match(r'https?://pixeldrain\.com/[du]/([a-zA-Z0-9]+)', url)
    if match:
        return f"https://pixeldrain.com/api/filesystem/{match.group(1)}?attach"
    return None

def get_current_time():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

async def get_local_titles():
    try:
        res = requests.get("https://app.ciptakode.my.id/getData.php")
        res.raise_for_status()
        data = res.json()
        if data.get("success"):
            return [{ "content_id": item["content_id"], "title": item["title"].lower() } for item in data["data"]]
    except Exception as e:
        print("❌ Gagal mengambil data dari server:", str(e))
    return []

async def scrape_kuramanime():
    local_titles = await get_local_titles()
    if not local_titles:
        print("❌ Tidak ada data lokal ditemukan.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36")
        page = await context.new_page()

        await page.goto("https://v6.kuramanime.run/quick/ongoing?order_by=updated", wait_until="networkidle")

        anime_list = await page.eval_on_selector_all(
            ".product__item", """
            nodes => nodes.map(n => {
                const linkElem = n.querySelector("h5 a");
                return {
                    title: linkElem ? linkElem.textContent.trim() : "Tidak ada judul",
                    link: linkElem ? linkElem.href : null
                };
            }).filter(item => item.link)
            """
        )

        for anime in anime_list:
            anime_title = anime["title"].lower()
            matched = next((x for x in local_titles if x["title"] == anime_title), None)
            if not matched:
                continue

            print(f"\n🎬 Judul: {anime['title']}")
            print(f"🆔 content_id: {matched['content_id']}")

            await page.goto(anime["link"], wait_until="networkidle")
            try:
                await page.wait_for_selector("#animeEpisodes a.ep-button", timeout=10000)
            except:
                print("   - Gagal menemukan daftar episode.")
                continue

            episodes = await page.eval_on_selector_all(
                "#animeEpisodes a.ep-button", """
                nodes => nodes.map(n => ({
                    episode: n.innerText.trim().replace(/\\s+/g, " "),
                    link: n.href
                }))
                """
            )

            for ep in episodes:
                print(f"   📺 Episode: {ep['episode']}")
                await page.goto(ep["link"], wait_until="networkidle")

                try:
                    await page.wait_for_selector("#animeDownloadLink", timeout=10000)
                except:
                    print("     - Gagal menemukan link download")
                    continue

                pixeldrain_links = await page.evaluate("""() => {
                    const container = document.querySelector("#animeDownloadLink");
                    if (!container) return null;
                    const result = {};
                    const headers = Array.from(container.querySelectorAll("h6.font-weight-bold")).filter(h =>
                        /mp4 480p/i.test(h.innerText) || /mp4 720p/i.test(h.innerText)
                    );

                    headers.forEach(header => {
                        const qualityText = header.innerText.trim();
                        let sib = header.nextElementSibling;
                        const urls = [];

                        while (sib && sib.tagName.toLowerCase() !== 'h6') {
                            if (sib.tagName.toLowerCase() === 'a' && sib.href.includes("pixeldrain.com")) {
                                urls.push(sib.href);
                            }
                            sib = sib.nextElementSibling;
                        }

                        if (urls.length > 0) {
                            result[qualityText] = urls;
                        }
                    });

                    return result;
                }""")

                if not pixeldrain_links:
                    print("     - Tidak ada link pixeldrain ditemukan")
                    continue

                url_480 = ""
                url_720 = ""
                for quality, links in pixeldrain_links.items():
                    converted_links = [convert_pixeldrain_url(l) or l for l in links]
                    print(f"     ▶ {quality}:")
                    for link in converted_links:
                        print(f"       • {link}")
                    if "480p" in quality.lower():
                        url_480 = converted_links[0]
                    if "720p" in quality.lower():
                        url_720 = converted_links[0]

                file_name = f"{anime['title']} {ep['episode']}"
                episode_number_match = re.search(r"\d+", ep["episode"])
                episode_number = int(episode_number_match.group(0)) if episode_number_match else 0

                try:
                    response = requests.post("https://app.ciptakode.my.id/insertEpisode.php", json={
                        "content_id": matched["content_id"],
                        "file_name": file_name,
                        "episode_number": episode_number,
                        "time": get_current_time(),
                        "view": 0,
                        "url_480": url_480,
                        "url_720": url_720,
                        "url_1080": "",
                        "url_1440": "",
                        "url_2160": "",
                        "title": anime["title"]
                    })
                    print("     ✅ Data berhasil dikirim:", response.text)
                except Exception as e:
                    print("     ❌ Gagal kirim ke server:", str(e))

        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_kuramanime())
