import playwright from "../../frontend/node_modules/playwright/index.js";

const { chromium } = playwright;

const email = "crm-git-001-invite@example.test";
const username = "crm-git-001-invite";
const password = "CrmGit001-Local-Only-42!";
const mailpit = "http://127.0.0.1:18025";
const keycloak = "http://127.0.0.1:18080";

const listingResponse = await fetch(`${mailpit}/api/v1/messages`);
if (!listingResponse.ok) throw new Error("mailpit_listing_failed");
const listing = await listingResponse.json();
const candidate = listing.messages.find((item) => JSON.stringify(item).includes(email));
if (!candidate) throw new Error("mailpit_message_missing");
const detailResponse = await fetch(`${mailpit}/api/v1/message/${candidate.ID}`);
if (!detailResponse.ok) throw new Error("mailpit_message_read_failed");
const detail = await detailResponse.json();
const message = `${detail.Text ?? ""}\n${detail.HTML ?? ""}`.replaceAll("&amp;", "&");
const link = message.match(/https?:\/\/[^\s<>"']+login-actions\/action-token[^\s<>"']+/)?.[0];
if (!link) throw new Error("keycloak_action_link_missing");

const browser = await chromium.launch({
  headless: true,
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
});
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(link, { waitUntil: "domcontentloaded" });
  const proceed = page.getByText(/click here to proceed/i);
  if (await proceed.count()) {
    await proceed.first().click();
  }
  await page.locator('input[name="password-new"]').waitFor({ state: "visible" });
  await page.locator('input[name="password-new"]').fill(password);
  await page.locator('input[name="password-confirm"]').fill(password);
  await page.locator('input[type="submit"], button[type="submit"]').first().click();
  await page.waitForTimeout(1000);

  const tokenResponse = await fetch(
    `${keycloak}/realms/aios/protocol/openid-connect/token`,
    {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "password",
        client_id: "aios-backend",
        username,
        password,
      }),
    },
  );
  if (!tokenResponse.ok) {
    const failure = await tokenResponse.json().catch(() => ({}));
    const adminTokenResponse = await fetch(
      `${keycloak}/realms/aios/protocol/openid-connect/token`,
      {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "client_credentials",
          client_id: "crm-inviter",
          client_secret: "crm-git-001-local-only",
        }),
      },
    );
    const adminToken = await adminTokenResponse.json();
    const userResponse = await fetch(
      `${keycloak}/admin/realms/aios/users?username=${encodeURIComponent(username)}&exact=true`,
      { headers: { authorization: `Bearer ${adminToken.access_token}` } },
    );
    const users = await userResponse.json();
    const state = users[0]
      ? `emailVerified=${users[0].emailVerified},requiredActions=${JSON.stringify(users[0].requiredActions)}`
      : "user_missing";
    throw new Error(
      `password_login_failed:${tokenResponse.status}:${failure.error ?? "unknown"}:` +
        `${failure.error_description ?? "no_description"}:${state}`,
    );
  }
  const token = await tokenResponse.json();
  if (!token.access_token) throw new Error("password_login_token_missing");

  const replayContext = await browser.newContext();
  const replayPage = await replayContext.newPage();
  await replayPage.goto(link, { waitUntil: "domcontentloaded" });
  if (await replayPage.locator('input[name="password-new"]').count()) {
    throw new Error("keycloak_action_link_reusable");
  }
  await replayContext.close();
  await context.close();
  console.log("keycloak_password_setup=true");
  console.log("keycloak_password_login=true");
  console.log("keycloak_action_link_one_time=true");
} finally {
  await browser.close();
}
