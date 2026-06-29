#!/usr/bin/env python3
"""
LegendaryCloud Discord Bot - Cloudflare + PAM System
"""

import discord
from discord.ext import commands
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
import re
import asyncio
import math
import os
import sys
import time
import random
import threading
import traceback

# ============================================================================
# CONFIGURATION
# ============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = 1384523041563869276
COMMAND_PREFIX = "?"
POKOPOW_BASE_URL = "https://pokopow.com"
SEARCH_URL_TEMPLATE = "https://pokopow.com/search/{query}"
AJAX_URL = "https://pokopow.com/wp-admin/admin-ajax.php"
DELETE_USER_MESSAGES = True
MINIMUM_CONSECUTIVE_CHARS = 3
MAX_SEARCH_RESULTS = 25
SEARCH_TIMEOUT = 30
CF_COOKIE_REFRESH_INTERVAL = 600  # Refresh cf_clearance every 10 minutes

BROWSER_IMPERSONATIONS = [
    'chrome124', 'chrome120', 'chrome116', 'chrome110',
    'chrome131', 'chrome136',
    'firefox133', 'firefox135',
]

# ============================================================================
# SCRAPER CLASS
# ============================================================================

class PokopowScraper:
    def __init__(self):
        self.cf_clearance = None
        self.user_agent = None
        self.cookies_initialized = False
        self.last_cookie_refresh = 0
        self._lock = threading.Lock()
    
    def _solve_cloudflare(self):
        """Start a real browser to solve Cloudflare Turnstile and get cf_clearance cookie.
        This runs synchronously in a thread.
        
        On headless hosters (like dein Hoster) ohne Browser, kannst du alternativ
        eine gültige cf_clearance per Umgebungsvariable setzen:
        
            export CF_CLEARANCE="wert..."
            export USER_AGENT="Mozilla/5.0 ..."
        
        Dann wird der Browser-Teil übersprungen.
        """
        # Prüfe ob cf_clearance als Umgebungsvariable gesetzt ist (für Headless-Hoster)
        env_cf = os.environ.get("CF_CLEARANCE", "")
        env_ua = os.environ.get("USER_AGENT", "")
        if env_cf:
            self.cf_clearance = env_cf
            self.user_agent = env_ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            self.cookies_initialized = True
            self.last_cookie_refresh = time.time()
            print(f"[Cloudflare] ✓ Using cf_clearance from environment variable!")
            return True
        
        try:
            from seleniumbase import Driver
        except ImportError:
            print("[Cloudflare] ✗ seleniumbase nicht installiert und keine CF_CLEARANCE env var gesetzt.")
            print("[Cloudflare]   Setze CF_CLEARANCE als Umgebungsvariable auf deinem Hoster!")
            return False
        
        driver = None
        try:
            print("[Cloudflare] Starting browser to solve Cloudflare challenge...")
            
            # Use headless mode - no visible browser window!
            # The uc_open_with_reconnect handles Turnstile automatically
            driver = Driver(uc=True, headless=True)
            
            # Step 1: Visit homepage (will trigger Cloudflare + redirect to ad)
            print("[Cloudflare] Visiting homepage...")
            driver.uc_open_with_reconnect(POKOPOW_BASE_URL, reconnect_time=4)
            time.sleep(2)
            
            # Step 2: Navigate to search page (this is where we get real cookies)
            print("[Cloudflare] Navigating to search page...")
            driver.get(SEARCH_URL_TEMPLATE.format(query='gta'))
            time.sleep(3)
            
            # Try clicking Turnstile if present
            try:
                if driver.is_element_visible('iframe[src*="turnstile"], iframe[src*="captcha"]'):
                    print("[Cloudflare] Detected Turnstile, attempting to click...")
                    driver.uc_gui_click_captcha()
                    time.sleep(2)
            except:
                pass
            
            # Check if we got past Cloudflare
            if 'Nur einen Moment' in driver.title or 'Just a moment' in driver.title:
                print("[Cloudflare] Still on challenge page, waiting more...")
                time.sleep(5)
            
            print(f"[Cloudflare] Current URL: {driver.current_url}")
            print(f"[Cloudflare] Title: {driver.title}")
            
            # Extract cookies
            selenium_cookies = driver.get_cookies()
            self.user_agent = driver.execute_script('return navigator.userAgent')
            
            cf = None
            for c in selenium_cookies:
                if c['name'] == 'cf_clearance':
                    cf = c['value']
                    break
            
            if cf:
                self.cf_clearance = cf
                self.cookies_initialized = True
                self.last_cookie_refresh = time.time()
                print(f"[Cloudflare] ✓ Got cf_clearance cookie! UA: {self.user_agent[:60]}...")
                return True
            else:
                print(f"[Cloudflare] ✗ No cf_clearance cookie found. Got {len(selenium_cookies)} cookies.")
                return False
                
        except Exception as e:
            print(f"[Cloudflare] Error: {type(e).__name__}: {e}")
            traceback.print_exc()
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
    
    def ensure_cookies(self):
        """Ensure we have valid cf_clearance cookies. Refresh if needed."""
        if not self.cookies_initialized:
            print("[Scraper] Initializing Cloudflare cookies...")
            return self._solve_cloudflare()
        
        # Refresh if older than interval
        if time.time() - self.last_cookie_refresh > CF_COOKIE_REFRESH_INTERVAL:
            print("[Scraper] Cookies expired, refreshing...")
            return self._solve_cloudflare()
        
        return True
    
    def _get_session(self):
        """Create a curl_cffi session with cf_clearance and random browser impersonation."""
        with self._lock:
            if not self.ensure_cookies():
                return None, None
        
        session = curl_requests.Session()
        
        # Set the cf_clearance cookie
        session.cookies.set('cf_clearance', self.cf_clearance, domain='.pokopow.com')
        
        # CHROME ONLY - das Cookie wurde mit Chrome gelöst, also nur Chrome verwenden!
        impersonate = 'chrome124'
        
        headers = {
            'User-Agent': self.user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': f'{POKOPOW_BASE_URL}/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Sec-CH-UA': '"Not_A Brand";v="8", "Chromium";v="124", "Google Chrome";v="124"',
            'Sec-CH-UA-Arch': 'x86',
            'Sec-CH-UA-Bitness': '64',
            'Sec-CH-UA-Full-Version-List': '"Not_A Brand";v="8.0.0.0", "Chromium";v="124.0.6367.91", "Google Chrome";v="124.0.6367.91"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': 'Windows',
            'Sec-CH-UA-Platform-Version': '15.0.0',
        }
        
        return session, impersonate
    
    def has_consecutive_chars_from_search(self, game_name, search_query, min_count=MINIMUM_CONSECUTIVE_CHARS):
        """Check if game name contains consecutive chars from search query"""
        clean_game = ''.join(c.lower() for c in game_name if c.isalpha())
        clean_query = ''.join(c.lower() for c in search_query if c.isalpha())
        
        for i in range(len(clean_query) - min_count + 1):
            substring = clean_query[i:i + min_count]
            if substring in clean_game:
                return True
        return False
    
    def search_games(self, query):
        """Search for games on pokopow.com"""
        try:
            original_query = query.strip()
            encoded_query = original_query.replace(' ', '-').lower()
            search_url = SEARCH_URL_TEMPLATE.format(query=encoded_query)
            
            print(f"Searching: {search_url}")
            time.sleep(0.5)  # Small delay to avoid rate limiting
            
            session, impersonate = self._get_session()
            if not session:
                print("Failed to get valid session")
                return []
            
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': f'{POKOPOW_BASE_URL}/',
                'Upgrade-Insecure-Requests': '1',
            }
            
            response = session.get(
                search_url,
                impersonate=impersonate,
                headers=headers,
                timeout=SEARCH_TIMEOUT
            )
            
            print(f"Search response: {response.status_code} (impersonating: {impersonate})")
            
            if response.status_code != 200:
                print(f"Search failed with status {response.status_code}")
                # Try to refresh cookies and retry once
                with self._lock:
                    self.cookies_initialized = False
                session, impersonate = self._get_session()
                if session:
                    response = session.get(
                        search_url,
                        impersonate=impersonate,
                        headers=headers,
                        timeout=SEARCH_TIMEOUT
                    )
                    print(f"Retry search: {response.status_code}")
            
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # DEBUG: Seite analysieren
            print(f"[Debug] Response size: {len(response.content)} bytes")
            print(f"[Debug] Page title: {soup.title.string if soup.title else 'N/A'}")
            
            # Find game links - the site uses elementor-post__thumbnail__link
            game_links = soup.find_all('a', class_='elementor-post__thumbnail__link')
            print(f"[Debug] elementor-post__thumbnail__link found: {len(game_links)}")
            
            # Also look for article links as fallback
            if not game_links:
                # Suche nach allen Links, die auf /search/ oder /game/ verweisen
                all_links = soup.find_all('a', href=True)
                pokopow_links = [a for a in all_links if a['href'].startswith(POKOPOW_BASE_URL) and a['href'] != POKOPOW_BASE_URL]
                print(f"[Debug] Total pokopow.com links on page: {len(pokopow_links)}")
                
                # Versuche es mit Artikel-Tags
                articles = soup.find_all('article')
                print(f"[Debug] <article> tags found: {len(articles)}")
                for article in articles:
                    h3 = article.find('h3')
                    if h3 and h3.find('a'):
                        game_links.append(h3.find('a'))
                
                # Letzter Versuch: CSS-Klasse 'post' oder 'game'
                if not game_links:
                    for cls in ['post', 'game', 'entry', 'card']:
                        posts = soup.find_all(class_=cls)
                        if posts:
                            print(f"[Debug] Found {len(posts)} elements with class '{cls}'")
                            for post in posts[:5]:  # nur erste 5
                                a = post.find('a', href=True)
                                if a and a['href'].startswith(POKOPOW_BASE_URL):
                                    game_links.append(a)
            
            if not game_links:
                print(f"[Debug] HTML snippet (first 1000 chars): {response.text[:1000]}")
            
            results = []
            for link in game_links:
                href = link.get('href')
                if href and href.startswith(POKOPOW_BASE_URL):
                    # Extract game name from URL
                    game_name = href.split('/')[-2] if href.endswith('/') else href.split('/')[-1]
                    game_name = game_name.replace('-', ' ').title()
                    
                    # Filter: only show games that contain 3+ consecutive chars from search query
                    if self.has_consecutive_chars_from_search(game_name, original_query):
                        results.append({
                            'name': game_name,
                            'url': href
                        })
            
            print(f"Found {len(results)} games for '{original_query}'")
            return results[:MAX_SEARCH_RESULTS]
            
        except Exception as e:
            print(f"Error searching games: {type(e).__name__}: {e}")
            traceback.print_exc()
            return []
    
    def extract_credentials(self, game_url):
        """Extract USER/PASS pairs from a game page using PAM AJAX system."""
        try:
            session, impersonate = self._get_session()
            if not session:
                return []
            
            # Step 1: Load the game page to get nonce and post_id
            print(f"Loading game page: {game_url}")
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': f'{POKOPOW_BASE_URL}/',
                'Upgrade-Insecure-Requests': '1',
            }
            
            response = session.get(game_url, impersonate=impersonate, headers=headers, timeout=SEARCH_TIMEOUT)
            
            if response.status_code != 200:
                print(f"Game page error: {response.status_code}")
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Step 2: Extract PAM parameters from the hidden div
            pam_box = soup.find('div', class_='pam-box')
            if not pam_box:
                print("No PAM box found - trying legacy extraction...")
                return self._extract_credentials_legacy(response.text)
            
            nonce = pam_box.get('data-pam-nonce', '')
            post_id = pam_box.get('data-pam-post-id', '')
            
            print(f"PAM params - post_id: {post_id}, nonce: {nonce[:20]}...")
            
            if not nonce or not post_id:
                print("Missing PAM parameters")
                return self._extract_credentials_legacy(response.text)
            
            # Step 3: Make AJAX request to get accounts
            ajax_headers = {
                'User-Agent': self.user_agent,
                'Referer': game_url,
                'Origin': POKOPOW_BASE_URL,
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
            }
            
            ajax_data = {
                'action': 'pam_load_accounts',
                'post_id': post_id,
                'nonce': nonce,
                'title': '',
            }
            
            print(f"Sending AJAX request to {AJAX_URL}")
            ajax_response = session.post(
                AJAX_URL,
                data=ajax_data,
                impersonate=impersonate,
                headers=ajax_headers,
                timeout=SEARCH_TIMEOUT
            )
            
            print(f"AJAX response: {ajax_response.status_code}")
            
            if ajax_response.status_code != 200:
                print("AJAX request failed")
                return self._extract_credentials_legacy(response.text)
            
            # Step 4: Parse the AJAX response
            try:
                result = ajax_response.json()
            except:
                print("AJAX response is not valid JSON")
                return self._extract_credentials_legacy(response.text)
            
            if not result.get('success') or not result.get('data', {}).get('html'):
                print(f"AJAX returned unsuccessful: {result}")
                return self._extract_credentials_legacy(response.text)
            
            # Step 5: Extract USER/PASS from the HTML response
            html_content = result['data']['html']
            cred_soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find all accordion items (each is one account)
            accordions = cred_soup.find_all('div', class_='pam-accordion')
            
            credentials = []
            for accordion in accordions:
                # Extract username
                username_input = accordion.find('input', class_='pam-input')
                if username_input:
                    user = username_input.get('value', '').strip()
                else:
                    continue
                
                # All inputs after the username one are password/other
                inputs = accordion.find_all('input', class_='pam-input')
                password = ''
                if len(inputs) >= 2:
                    password = inputs[1].get('value', '').strip()
                
                if user and password:
                    credentials.append({
                        'user': user,
                        'pass': password
                    })
            
            # Remove duplicates
            unique_creds = []
            seen = set()
            for cred in credentials:
                cred_key = (cred['user'].lower(), cred['pass'].lower())
                if cred_key not in seen:
                    seen.add(cred_key)
                    unique_creds.append(cred)
            
            game_name = game_url.split('/')[-2] if game_url.endswith('/') else game_url.split('/')[-1]
            print(f"✓ Found {len(unique_creds)} accounts for {game_name}")
            
            return unique_creds
            
        except Exception as e:
            print(f"Error extracting credentials: {type(e).__name__}: {e}")
            traceback.print_exc()
            return []
    
    def _extract_credentials_legacy(self, html_text):
        """Fallback: Try to extract credentials directly from HTML (old format)."""
        credentials = []
        soup = BeautifulSoup(html_text, 'html.parser')
        
        # Look for text holders
        text_holders = soup.find_all('div', class_='pagelayer-text-holder')
        
        for holder in text_holders:
            holder_text = holder.get_text()
            patterns = [
                r'USER\s*:\s*([^\n\r<]+).*?PASS\s*:\s*([^\n\r<]+)',
                r'Username\s*:\s*([^\n\r<]+).*?Password\s*:\s*([^\n\r<]+)',
                r'Login\s*:\s*([^\n\r<]+).*?Pass\s*:\s*([^\n\r<]+)',
            ]
            for pattern in patterns:
                matches = re.finditer(pattern, holder_text, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    user = match.group(1).strip()
                    password = match.group(2).strip()
                    if user and password and user != ':' and password != ':':
                        credentials.append({'user': user, 'pass': password})
        
        # Also try direct page text
        page_text = soup.get_text()
        additional_patterns = [
            r'USER\s*:\s*([^\s\n]+)\s*.*?PASS\s*:\s*([^\s\n]+)',
            r'Username\s*:\s*([^\s\n]+)\s*.*?Password\s*:\s*([^\s\n]+)',
            r'Login\s*:\s*([^\s\n]+)\s*.*?Pass\s*:\s*([^\s\n]+)',
        ]
        for pattern in additional_patterns:
            matches = re.finditer(pattern, page_text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                user = match.group(1).strip()
                password = match.group(2).strip()
                if user and password and len(user) > 1 and len(password) > 1:
                    credentials.append({'user': user, 'pass': password})
        
        # Remove duplicates
        unique_creds = []
        seen = set()
        for cred in credentials:
            cred_key = (cred['user'].lower(), cred['pass'].lower())
            if cred_key not in seen:
                seen.add(cred_key)
                unique_creds.append(cred)
        
        print(f"Legacy extraction: found {len(unique_creds)} accounts")
        return unique_creds


# ============================================================================
# PAGINATION SYSTEM
# ============================================================================

class CredentialPaginator(discord.ui.View):
    def __init__(self, credentials, game_name, game_url, user, items_per_page=3):
        super().__init__(timeout=300)
        self.credentials = credentials
        self.game_name = game_name
        self.game_url = game_url
        self.user = user
        self.items_per_page = items_per_page
        self.current_page = 0
        self.credentials = credentials
        self.max_pages = math.ceil(len(self.credentials) / items_per_page) if self.credentials else 1
        
        self.update_buttons()
    
    def update_buttons(self):
        self.clear_items()
        
        if self.max_pages > 1:
            # Previous button (Blurple style)
            if self.current_page > 0:
                self.add_item(PrevPageButton())
            
            # Page indicator as a disabled button
            page_btn = discord.ui.Button(
                style=discord.ButtonStyle.gray,
                label=f"{self.current_page + 1} / {self.max_pages}",
                disabled=True
            )
            self.add_item(page_btn)
            
            # Next button
            if self.current_page < self.max_pages - 1:
                self.add_item(NextPageButton())
    
    def get_current_embed(self):
        if not self.credentials:
            embed = discord.Embed(
                title=f"**{self.game_name}**",
                description="No accounts found for this game yet. Try another title!",
                color=0xFF4757,
                url=self.game_url
            )
            embed.set_footer(text="LegendaryCloud")
            return embed
        
        # REVERSE so LATEST is first
        reversed_creds = list(reversed(self.credentials))
        
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(reversed_creds))
        page_credentials = reversed_creds[start_idx:end_idx]
        
        total_creds = len(self.credentials)
        
        embed = discord.Embed(
            title=f"**{self.game_name}**",
            description=f"Vault unlocked: **{total_creds}** account(s) | Page **{self.current_page + 1}/{self.max_pages}**",
            color=0xFFD700,
            url=self.game_url
        )
        
        for i, cred in enumerate(page_credentials):
            account_num = start_idx + i + 1
            embed.add_field(
                name=f"**ACCOUNT #{account_num:02d}**",
                value=f"**USER:** `{cred['user']}`\n**PASS:** `{cred['pass']}`",
                inline=True
            )
        
        embed.set_footer(text="LegendaryCloud")
        embed.timestamp = discord.utils.utcnow()
        
        return embed

class PrevPageButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="<  Previous"
        )
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.user.id:
            await interaction.response.send_message("This vault belongs to someone else!", ephemeral=True)
            return
            
        view = self.view
        if view.current_page > 0:
            view.current_page -= 1
            view.update_buttons()
            embed = view.get_current_embed()
            await interaction.response.edit_message(embed=embed, view=view)

class NextPageButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Next >"
        )
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.user.id:
            await interaction.response.send_message("This vault belongs to someone else!", ephemeral=True)
            return
            
        view = self.view
        if view.current_page < view.max_pages - 1:
            view.current_page += 1
            view.update_buttons()
            embed = view.get_current_embed()
            await interaction.response.edit_message(embed=embed, view=view)

# ============================================================================
# UI COMPONENTS
# ============================================================================

class GameSelectView(discord.ui.View):
    def __init__(self, search_results, scraper, user):
        super().__init__(timeout=300)
        self.search_results = search_results
        self.scraper = scraper
        self.user = user
        self.search_message = None
        
        options = []
        for i, result in enumerate(search_results[:25]):
            options.append(
                discord.SelectOption(
                    label=result['name'][:100],
                    description=f"Click to get accounts for {result['name']}"[:100],
                    value=str(i)
                )
            )
        
        if options:
            select = GameSelect(options, self.scraper, self.user)
            self.add_item(select)

class GameSelect(discord.ui.Select):
    def __init__(self, options, scraper, user):
        super().__init__(
            placeholder="Choose a game to get accounts...",
            options=options,
            row=0
        )
        self.scraper = scraper
        self.user = user
    
    async def callback(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != self.user.id:
                await interaction.response.send_message("This vault belongs to someone else!", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            selected_index = int(self.values[0])
            selected_game = self.view.search_results[selected_index]
            
            # Run credential extraction in thread to not block Discord
            credentials = await asyncio.to_thread(
                self.scraper.extract_credentials, selected_game['url']
            )
            
            paginator = CredentialPaginator(credentials, selected_game['name'], selected_game['url'], self.user)
            embed = paginator.get_current_embed()
            
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)
            
            # Delete search results message
            if self.view.search_message:
                try:
                    await self.view.search_message.delete()
                except:
                    pass
            
        except Exception as e:
            error_embed = discord.Embed(
                title="**Something Broke**",
                description=(
                    f"> An unexpected error occurred while unlocking this vault.\n\n"
                    f"```\n{str(e)}\n```\n\n"
                    "Try again or contact support if this persists."
                ),
                color=0xFF4757
            )
            error_embed.set_footer(text="LegendaryCloud")
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            
            if self.view.search_message:
                try:
                    await self.view.search_message.delete()
                except:
                    pass


def create_panel_embed():
    embed = discord.Embed(
        description=(
            "**How to Search**\n"
            "Simply type a game name below — 1-2 words is all it takes:\n\n"
            "- `Grand Theft`\n"
            "- `God of War`\n"
            "- `Assassin's Creed`"
        ),
        color=0x6C3CE0
    )
    embed.set_footer(text="LegendaryCloud • Your Gateway to Premium Game Accounts")
    return embed

def create_search_results_embed(query, results, user):
    if not results:
        embed = discord.Embed(
            title="**No Results**",
            description=(
                f"No games found for: **{query}**\n\n"
                "Tips:\n"
                "- Try shorter keywords (e.g. `GTA` instead of `Grand Theft Auto`)\n"
                "- Check your spelling\n"
                "- Use the game's main title"
            ),
            color=0xFF4757
        )
        embed.set_footer(text="LegendaryCloud")
    else:
        results_list = "\n".join([
            f"**{i}.** [{r['name']}]({r['url']})"
            for i, r in enumerate(results[:10], 1)
        ])
        
        more = f"\n*...and {len(results) - 10} more*" if len(results) > 10 else ""
        
        embed = discord.Embed(
            title="**Search Results**",
            description=(
                f"Found **{len(results)}** game(s) for: **{query}**\n\n"
                f"{results_list}{more}\n\n"
                "---\n"
                "Select a game from the dropdown below to view accounts."
            ),
            color=0x00D4AA
        )
        embed.set_footer(text=f"LegendaryCloud • Requested by {user.display_name}")
        embed.timestamp = discord.utils.utcnow()
    
    return embed

# ============================================================================
# BOT SETUP
# ============================================================================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

# Initialize scraper
scraper = PokopowScraper()

@bot.event
async def on_ready():
    print(f'{bot.user} has logged in successfully!')
    print(f'Bot ID: {bot.user.id}')
    print(f'Monitoring Channel ID: {CHANNEL_ID}')
    print(f'Command Prefix: {COMMAND_PREFIX}')
    
    # Initialize Cloudflare cookies in background
    print('Initializing Cloudflare bypass...')
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, scraper._solve_cloudflare)
    if success:
        print('✓ Cloudflare bypass initialized successfully!')
    else:
        print('⚠ Cloudflare bypass initialization had issues. Will retry on first search.')
    
    print('Bot is ready to serve the LegendaryCloud!')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send("❌ Channel not found!", delete_after=300)
    else:
        print(f"Command error: {error}")
        await ctx.send(f"❌ An error occurred: {str(error)}", delete_after=300)

@bot.command(name='panel')
async def panel_command(ctx):
    if ctx.channel.id != CHANNEL_ID:
        return
    embed = create_panel_embed()
    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    if message.channel.id != CHANNEL_ID:
        return
    
    await bot.process_commands(message)
    
    if message.content.startswith(COMMAND_PREFIX):
        return
    
    if not message.content.strip():
        return
    
    try:
        # Wait before deleting to avoid client-side visual bugs
        await asyncio.sleep(2)
        await message.delete()
        
        query = message.content.strip()
        
        # Run search in thread pool to not block
        search_results = await asyncio.to_thread(scraper.search_games, query)
        
        embed = create_search_results_embed(query, search_results, message.author)
        
        if search_results:
            view = GameSelectView(search_results, scraper, message.author)
            
            search_msg = await message.channel.send(
                embed=embed, 
                view=view,
                delete_after=60
            )
            view.search_message = search_msg
        else:
            await message.channel.send(
                embed=embed,
                delete_after=60
            )
    
    except discord.errors.NotFound:
        pass
    except discord.errors.Forbidden:
        print("Bot doesn't have permission to delete messages")
    except Exception as e:
        print(f"Error processing message: {type(e).__name__}: {e}")
        error_embed = discord.Embed(
            title="**Search Error**",
            description=(
                f"> The search encountered an unexpected issue.\n\n"
                f"```\n{str(e)}\n```\n\n"
                "Try again or use a different search term."
            ),
            color=0xFF4757
        )
        error_embed.set_footer(text="LegendaryCloud")
        await message.channel.send(embed=error_embed, delete_after=300)

@bot.command(name='help')
async def help_command(ctx):
    if ctx.channel.id != CHANNEL_ID:
        return
    
    embed = discord.Embed(
        title="**Help & Commands**",
        description=(
            "> Everything you need to know about the LegendaryCloud\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**Searching Games**\n"
            "Just **type any game name** in the chat — that's it!\n"
            "> • Use 1-2 words for best results\n"
            "> • Example: `God of War`, `GTA`, `Assassin`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**⚙️ Commands**\n\n"
            f"`{COMMAND_PREFIX}panel` — Show the main search panel\n"
            f"`{COMMAND_PREFIX}help` — Show this help menu\n"
            f"`{COMMAND_PREFIX}status` — Check bot status\n"
            f"`{COMMAND_PREFIX}refresh` — Refresh Cloudflare session\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "**How It Works**\n"
            "1️⃣ Type a game name → 2️⃣ Search results appear\n"
            "3️⃣ Select from dropdown → 4️⃣ Get accounts **privately** ✅"
        ),
        color=0x6C3CE0
    )
    embed.set_thumbnail(url="https://i.ibb.co/Lp99s5G/key-icon.png")
    embed.set_footer(text="LegendaryCloud")
    
    await ctx.send(f"<@{ctx.author.id}>", embed=embed, delete_after=300)

@bot.command(name='status')
async def status_command(ctx):
    if ctx.channel.id != CHANNEL_ID:
        return
    
    cf_status = "✅ Operational" if scraper.cookies_initialized else "❌ Needs Refresh"
    avatar_url = ctx.me.display_avatar.url if ctx.me else discord.Embed.Empty
    
    embed = discord.Embed(
        title="**System Status**",
        description=(
            "> All systems are running smoothly.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        ),
        color=0x2ED573
    )
    
    embed.add_field(
        name="**Cloudflare**",
        value=f"> {cf_status}\n> Session active since last refresh",
        inline=True
    )
    
    embed.add_field(
        name="⚙️ **Configuration**",
        value=f"> Channel: `{CHANNEL_ID}`\n> Prefix: `{COMMAND_PREFIX}`",
        inline=True
    )
    
    embed.add_field(
        name="**Privacy**",
        value="> All accounts delivered\n> via ephemeral messages",
        inline=False
    )
    
    embed.set_footer(
        text="LegendaryCloud",
        icon_url=avatar_url
    )
    embed.timestamp = discord.utils.utcnow()
    
    await ctx.send(f"<@{ctx.author.id}>", embed=embed, delete_after=300)

@bot.command(name='refresh')
async def refresh_command(ctx):
    """Manually refresh Cloudflare cookies"""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    loading = discord.Embed(
        title="**Refreshing Session**",
        description=(
            "> Re-authenticating with Cloudflare...\n\n"
            "⏳ *This takes about 10-15 seconds*"
        ),
        color=0x6C3CE0
    )
    loading.set_footer(text="LegendaryCloud")
    msg = await ctx.send(embed=loading, delete_after=30)
    
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, scraper._solve_cloudflare)
    
    if success:
        embed = discord.Embed(
            title="✅ **Session Refreshed**",
            description=(
                "> Cloudflare authentication renewed successfully!\n\n"
                "> New cf_clearance cookie obtained.\n"
                "> The bot is ready to serve."
            ),
            color=0x2ED573
        )
        embed.set_footer(text="LegendaryCloud")
        await msg.edit(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ **Refresh Failed**",
            description=(
                "> Could not re-authenticate with Cloudflare.\n\n"
                "Try running the bot on a machine with a display, or check your internet connection."
            ),
            color=0xFF4757
        )
        embed.set_footer(text="LegendaryCloud")
        await msg.edit(embed=embed)

# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main():
    
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("=" * 50)
        print("❌ FEHLER: Kein Bot-Token gesetzt!")
        print("=" * 50)
        print("So bekommst du einen Token:")
        print("  1. Gehe zu https://discord.com/developers/applications")
        print("  2. Erstelle eine neue Application > Bot > Create Bot")
        print("  3. Kopiere den Token in die BOT_TOKEN Variable in main.py")
        print("=" * 50)
        sys.exit(1)
    
    try:
        print("Starting LegendaryCloud Discord Bot...")
        bot.run(BOT_TOKEN)
    except discord.LoginFailure:
        print("❌ FEHLER: Ungültiger Bot-Token!")
        print("Bitte überprüfe deinen BOT_TOKEN in main.py")
        sys.exit(1)
    except Exception as e:
        print(f"❌ FEHLER: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
