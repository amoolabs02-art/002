const express = require('express');
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');

puppeteer.use(StealthPlugin());

const app = express();
const PORT = 3000;

async function solveTurnstile(targetUrl) {
    const browser = await puppeteer.launch({
        headless: 'new',
        executablePath: '/usr/bin/google-chrome',
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-blink-features=AutomationControlled',
            '--disable-software-rasterizer',
        ],
    });

    try {
        const page = await browser.newPage();
        await page.setViewport({ width: 1920, height: 1080 });
        await page.setUserAgent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        );

        for (let attempt = 0; attempt < 3; attempt++) {
            console.log(`[Solver] Attempt ${attempt + 1}/3...`);
            await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
            await page.waitForTimeout(10000);

            const title = await page.title();
            if (!title.includes('Just a moment') && !title.includes('Nur einen Moment')) {
                console.log(`[Solver] ✓ Challenge solved!`);
                break;
            }
            console.log(`[Solver] Still blocked (attempt ${attempt + 1})`);
            await page.evaluate(() => { document.cookie.split(';').forEach(c => { document.cookie = c.trim().split('=')[0] + '=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/'; }); });
            await page.waitForTimeout(3000);
        }

        const searchUrl = targetUrl.replace(/\/?$/, '') + '/search/gta';
        await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
        await page.waitForTimeout(5000);

        const cookies = await page.cookies();
        const userAgent = await page.evaluate(() => navigator.userAgent);
        const cfClearance = cookies.find(c => c.name === 'cf_clearance');

        console.log(`[Solver] Cookies found: ${cookies.length}, cf_clearance: ${!!cfClearance}`);

        return {
            title: await page.title(),
            userAgent: userAgent,
            cookie: cfClearance ? `cf_clearance=${cfClearance.value}` : null,
            success: !!cfClearance,
            cookies: cookies.map(c => c.name),
        };

    } catch (error) {
        console.error(`[Solver] Error: ${error.message}`);
        return { success: false, error: error.message };
    } finally {
        await browser.close();
    }
}

app.get('/api', async (req, res) => {
    const target = req.query.target;
    if (!target) return res.status(400).json({ success: false, error: 'Missing target' });
    console.log(`[API] Solving: ${target}`);
    const result = await solveTurnstile(target);
    console.log(`[API] Result: ${result.success ? '✓' : '✗'}`);
    res.json(result);
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.listen(PORT, '127.0.0.1', () => {
    console.log(`[Server] captchaSolver ready on port ${PORT}`);
});
