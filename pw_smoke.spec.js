const { test, expect } = require('playwright/test');

test('smoke', async ({ page }) => {
  await page.goto('https://agency.magnifytools.com', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveTitle(/Magnify/i);
});
