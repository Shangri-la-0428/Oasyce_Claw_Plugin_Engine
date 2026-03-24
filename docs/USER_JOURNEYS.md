# Oasyce Dashboard 用户旅程图 (User Journey Map)

> Comprehensive user journey documentation for the Oasyce Dashboard (`localhost:8420`).
> Bilingual format: Chinese headings, English detail. Aligned with PRD v2.1.1 QA spec.

**Version**: v1.0.0 | **Last updated**: 2026-03-25 | **Journeys**: 8 | **QA Checkpoints**: QA-3001 -- QA-3099

---

## 系统页面关系图 (Page Relationship Diagram)

```
                         ┌─────────────────────────────────────┐
                         │          Dashboard Entry             │
                         │        localhost:8420                 │
                         └──────────────┬──────────────────────┘
                                        │
                         ┌──────────────▼──────────────────────┐
                         │     Home (onboarding / veteran)      │
                         │  NetworkGrid + Hero + Steps/Status   │
                         └──┬───────┬───────┬──────────────┬───┘
                            │       │       │              │
              ┌─────────────▼─┐  ┌──▼─────────┐  ┌────────▼──────┐
              │  My Data       │  │  Explore    │  │  Network      │
              │  (manage)      │  │  (browse)   │  │  (configure)  │
              └──┬──────┬─────┘  └──┬──────┬───┘  └───────────────┘
                 │      │           │      │
                 │   ┌──▼───────┐  │   ┌──▼──────────┐
                 │   │ Register  │  │   │ Portfolio /  │
                 │   │ (inline)  │  │   │ Stake        │
                 │   └──┬───────┘  │   └──────────────┘
                 │      │           │
              ┌──▼──────▼───────────▼──────────────────┐
              │              Automation                  │
              │    Queue (inbox) + Rules (agent)         │
              └─────────────────────────────────────────┘

 ═══ Cross-page flows ═══

 Register ──→ My Data ──→ Market ──→ Purchase ──→ Earnings (Home)
    │                                     │
    └──→ Success banner ──→ Copy ID       └──→ Portfolio (Explore)

 Scan (Automation) ──→ Inbox ──→ Approve ──→ My Data

 Notification bell ──→ Click ──→ Navigate to relevant page
```

---

## Journey 1: 新用户上手 (New User Onboarding)

### 前置条件 (Preconditions)

- Node backend running (`oas start` completed, serving on `localhost:8420`)
- No wallet exists locally (fresh install or first visit)
- Network reachable for PoW puzzle submission
- Browser supports modern JS (Preact + Vite bundle)

### 步骤流 (Step-by-step Flow)

```
 1. Open browser                     6. PoW mining starts           11. Mode switch appears
 2. See NetworkGrid animation        7. Wallet created (toast)      12. Fill register form
 3. Read hero text                   8. Focus moves to funds gate   13. Upload file / enter cap
 4. Review steps indicator           9. Click "Register" (PoW)     14. Submit → Success
 5. Click "Create Wallet"           10. Receive starter OAS         15. Choose next action
```

**Detailed steps:**

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Opens `localhost:8420` | Dashboard loads, dark theme default | `main.tsx` → `app.tsx` router |
| 2 | Sees ambient animation | NetworkGrid renders cellular automata | `<NetworkGrid />` in `.home-grid-wrap` |
| 3 | Reads hero headline | `hero-title-light` + `hero-title-bold` display | `.home-hero .display` |
| 4 | Sees step indicator: Step 1 active (01 highlighted, 02/03 dimmed) | `currentStep = 1` because `!walletExists` | Steps strip with `.active` class |
| 5 | Clicks "Create Wallet" button | `setCreatingWallet(true)`, calls `POST /api/identity/create` | `.btn-primary` in wallet gate section |
| 6 | Sees loading spinner on button | PoW puzzle solving happens server-side | Button disabled state |
| 7 | Wallet created | Toast: "Wallet created" (success). `loadIdentity()` + `loadBalance()` refresh signals. Step 1 shows masked address. | `showToast()` → `<Toast />` |
| 8 | Focus auto-shifts to funds gate | `gateRef.current.focus()` via `requestAnimationFrame` | Funds gate `<Section>`, `currentStep = 2` |
| 9 | Clicks "Register" (PoW self-registration) | `selfRegister()` fires `POST /api/onboarding/register`. Mining progress shown via `powProgress` signal. | Funds gate button, progress indicator |
| 10 | PoW completes, starter OAS received | Toast: "Received {amount} OAS". `loadBalance()` updates. Step 2 shows balance. | `showToast()`, balance signal update |
| 11 | Step 3 activates; mode switch appears | `currentStep = 3`. Data/Capability tablist renders. | `.home-mode-switch` with `role="tablist"` |
| 12 | Selects "Data" tab (default), fills form | RegisterForm renders: dropzone, description field, rights type selector, price model selector. Co-creator fields appear for `co_creation` rights. | `<RegisterForm mode="data" />` |
| 13 | Drags file into dropzone | File validated (type, size). Single file → `POST /api/register`. Multiple files → `POST /api/register-bundle`. Upload progress shown. | `.dropzone` component, `postFile()` / `postBundle()` |
| 14 | Clicks "Register" button | Upload completes. Success callback fires `handleSuccess()`. Toast: "Data asset registered". | `.btn-primary`, success banner |
| 15 | Sees success banner with asset details | Shows `asset_id` (masked), `file_hash` (masked), `price_model`, registration type. Four action buttons appear. | Success section with `.kv` rows |
| 16 | Chooses next action | Options: "View My Data" → `go('mydata')`, "Open Market" → `go('explore')`, "Copy ID" → clipboard, "Register Another" → reset form | Navigation buttons |

### 触点 (UI Touchpoints)

| Touchpoint | Component | File |
|------------|-----------|------|
| NetworkGrid ambient animation | `<NetworkGrid />` | `src/components/network-grid.tsx` |
| Hero text block | `.home-hero .display` | `src/pages/home.tsx` |
| Steps indicator (01/02/03) | Steps strip in onboarding view | `src/pages/home.tsx` |
| Wallet gate section | `<Section>` with create button | `src/pages/home.tsx` |
| Funds gate section | `<Section>` with register button | `src/pages/home.tsx` |
| Mode switch (Data/Capability) | `.home-mode-switch` tablist | `src/pages/home.tsx` |
| RegisterForm | `<RegisterForm />` | `src/components/register-form.tsx` |
| Dropzone | `.dropzone` within RegisterForm | `src/components/register-form.tsx` |
| Success banner | Result rows + action buttons | `src/pages/home.tsx` |
| Toast notifications | `<Toast />` | `src/components/toast.tsx` |

### API 调用 (API Calls)

| Step | Method | Endpoint | Request Body | Response |
|------|--------|----------|-------------|----------|
| 5 | POST | `/api/identity/create` | `{}` | `{ ok: true, address: "oasyce1...", created: true }` |
| 9 | POST | `/api/onboarding/register` | `{}` | `{ ok: true, amount: 40.0 }` (testnet: 40 OAS) |
| 13a | POST | `/api/register` | FormData: `file`, `owner`, `description`, `tags`, `rights_type`, `price_model` | `{ asset_id, file_hash, price_model }` |
| 13b | POST | `/api/register-bundle` | FormData: `files[]`, same fields | `{ asset_id, file_count, price_model }` |

### 状态变更 (State Changes)

| Signal | Before | After | Trigger |
|--------|--------|-------|---------|
| `identity` | `null` | `{ address: "oasyce1...", exists: true }` | Step 7: `loadIdentity()` |
| `balance` | `null` | `40.0` | Step 10: `loadBalance()` |
| `assets` | `[]` | `[{ asset_id, ... }]` | Step 14: `loadAssets()` |
| `walletExists` (derived) | `false` | `true` | After identity load |
| `hasStarterFunds` (derived) | `false` | `true` | After balance load |
| `isVeteran` (derived) | `false` | `true` | After first asset registered |
| `currentStep` (derived) | `1` | `2` → `3` | Progressive unlock |

### 错误分支 (Error Branches)

| Error | Trigger | User Sees | Recovery |
|-------|---------|-----------|----------|
| **Network error during wallet creation** | `POST /identity/create` fails (timeout/network) | Toast: "Network error" (error-network i18n key). Button re-enables. | Retry click. `withTimeout(30_000)` provides 30s window. |
| **Wallet already exists** | Identity exists on server | Toast: "Wallet already exists" (info). Steps advance past step 1. | Normal flow continues; not a true error. |
| **Network error during PoW** | `POST /onboarding/register` fails | Toast: "Network error". `claiming` resets to false. | Retry. PoW puzzle is stateless; new attempt starts fresh. |
| **PoW timeout** | Mining takes >30s (high difficulty) | Toast: "Request timeout" (error-timeout). | Retry. Server adjusts difficulty for testnet. |
| **Empty file upload** | User selects 0-byte file | Validation prevents submission (file.size === 0). | Select a non-empty file. |
| **File too large** | File exceeds server limit | Server returns 413; toast shows error. | Use smaller file or split into bundle. |
| **Invalid file format** | Server rejects file type | Toast: server error message. Form remains populated. | Choose supported format. |
| **Upload timeout** | `postFile()` exceeds 120s | Toast: "Request timeout". | Retry with smaller file or better connection. |
| **Server error (500)** | Backend crash during registration | Toast: "Server error" (error-server). | Check backend logs, retry. |
| **Rate limited (429)** | Too many requests in window | Toast: "Rate limited" (error-rate-limit). | Wait, retry after cooldown (default: write 20/min). |

### 情感曲线 (Emotional Arc)

```
Excitement ▲
           │        ★ Wallet created!
           │       ╱                    ★ OAS received!
           │      ╱                    ╱              ★ First asset!
           │     ╱   Anticipation     ╱              ╱
           │    ╱     (PoW wait)     ╱   Building   ╱
           │   ╱                    ╱   confidence  ╱   Accomplishment
           │  ╱                    ╱              ╱   ╱
   Curiosity ╱──────────────────╱──────────────╱───╱──────────→
           │                                                    Time
           │  "What is this?" → "My identity!" → "I have funds" → "I own an asset!"
```

**Curiosity** (landing, reading hero) → **Anticipation** (waiting for PoW) → **Confidence** (funds received) → **Accomplishment** (first asset registered, seeing success banner with real data)

### 验证点 (Verification Points)

| QA ID | Check | Expected |
|-------|-------|----------|
| QA-3001 | NetworkGrid renders on first load | Canvas visible, animation running |
| QA-3002 | Hero text displays in current language | `hero-title-light` + `hero-title-bold` match `lang` signal |
| QA-3003 | Steps indicator shows step 1 active for new user | `currentStep === 1`, first step has `.active` class |
| QA-3004 | "Create Wallet" button visible and clickable | Button rendered, not disabled |
| QA-3005 | POST /identity/create returns `ok: true` | Response includes `address` field |
| QA-3006 | Toast appears on wallet creation | Success toast with wallet-created message |
| QA-3007 | Focus moves to funds gate after wallet | `document.activeElement` is within funds gate section |
| QA-3008 | PoW self-registration succeeds | `selfRegister()` returns `ok: true`, amount > 0 |
| QA-3009 | Balance updates after PoW | `balance.value > 0` |
| QA-3010 | Step 3 activates after funds received | `currentStep === 3`, register form visible |
| QA-3011 | Mode switch renders Data/Capability tabs | Tablist with two tabs, Data selected by default |
| QA-3012 | File upload via dropzone works | File accepted, form populated |
| QA-3013 | POST /register returns asset_id | Response includes `asset_id`, `file_hash` |
| QA-3014 | Success banner shows masked asset_id | `mask(asset_id, 12, 8)` displayed |
| QA-3015 | All four action buttons work after success | Navigation to mydata/explore, clipboard copy, form reset |

---

## Journey 2: 老用户回访 (Veteran Return Visit)

### 前置条件 (Preconditions)

- Wallet exists (`identity.exists === true`)
- Balance > 0 (`hasStarterFunds === true`)
- At least one registered asset (`assets.length > 0`)
- These three conditions make `isVeteran = true` in `home.tsx`

### 步骤流 (Step-by-step Flow)

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Opens `localhost:8420` | Home page renders. `isVeteran && !done` triggers veteran branch. | `home.tsx` veteran view |
| 2 | Sees NetworkGrid + hero | Same ambient animation, but hero shows "Open market" / "View network" buttons instead of "Create Wallet" | `.home-grid-wrap`, `.home-hero` |
| 3 | Reviews status strip | Four KV pairs: Wallet (masked address), Balance (OAS), Assets (count), Earnings (total OAS) | `.home-status` with `.kv` elements |
| 4 | Earnings load async | `GET /api/earnings?owner={addr}` fetches total_earned + transactions. Loading state → data. | `ownerEarnings` state, `earningsFetched` ref guard |
| 5 | Reviews recent trades | Trades list shows `asset_id`, `buyer`, `amount`, `timestamp` for each transaction. "No trades yet" if empty. | `.home-trades` section |
| 6 | Navigates via action buttons | "Open market" → `go('explore')`, "View network" → `go('network')` | `.btn-primary`, `.btn-ghost` |
| 7 | Or navigates via nav rows | Three nav rows: My Data, Explore, Network -- each with title + description | `.home-navigate nav` with `.nav-row` buttons |
| 8 | Or clicks "Register more" | Expands inline register form with mode switch (Data/Capability) | `.home-mode-switch` + `<RegisterForm />` |

### 触点 (UI Touchpoints)

| Touchpoint | Component | Purpose |
|------------|-----------|---------|
| Status strip | `.home-status` with 4x `.kv` | At-a-glance account health |
| Earnings display | `.kv` for total, `.home-trades` for list | Revenue tracking |
| Recent trades list | Trade rows with masked buyer/asset | Activity awareness |
| Hero action buttons | `.btn-primary` + `.btn-ghost` | Primary navigation |
| Nav rows | `.nav-row` buttons in `.home-navigate` | Secondary navigation with descriptions |
| Register more section | `<RegisterForm />` inline | Quick re-registration |

### API 调用 (API Calls)

| Trigger | Method | Endpoint | Notes |
|---------|--------|----------|-------|
| Page load | GET | `/api/identity` | Via `loadIdentity()` in `store/ui.ts` |
| Page load | GET | `/api/balance` | Via `loadBalance()` in `store/ui.ts` |
| Page load | GET | `/api/assets` | Via `loadAssets()` in `store/assets.ts` |
| Veteran detected | GET | `/api/earnings?owner={addr}` | Guarded by `earningsFetched` ref to prevent re-fetch |

### 状态变更 (State Changes)

| Signal | Initial | After Load | Notes |
|--------|---------|-----------|-------|
| `identity` | cached or null | `{ address, exists: true }` | Persists across navigations |
| `balance` | cached or null | Current OAS balance | Refreshed on page load |
| `assets` | `[]` | Full asset list | Refreshed on page load |
| `ownerEarnings` (local) | `null` | `{ total_earned, transactions[] }` | One-time fetch per session |

### 错误分支 (Error Branches)

| Error | Trigger | User Sees | Recovery |
|-------|---------|-----------|----------|
| **Earnings fetch fails** | `/earnings` endpoint error | Earnings show "0.0 OAS" (fallback). Non-critical. | Refresh page. |
| **Assets load fails** | `/assets` endpoint error | Empty asset count. May falsely show onboarding view. | Refresh. Backend may be restarting. |
| **Stale wallet** | Wallet existed but was deleted server-side | `walletExists` false, falls back to onboarding. | Re-create wallet via onboarding flow. |

### 情感曲线 (Emotional Arc)

**Recognition** (familiar layout) → **Satisfaction** (seeing earnings + balance) → **Motivation** (register more, explore market)

### 验证点 (Verification Points)

| QA ID | Check | Expected |
|-------|-------|----------|
| QA-3016 | Veteran view renders when all 3 conditions met | `isVeteran === true`, no steps indicator, status strip visible |
| QA-3017 | Status strip shows 4 KV pairs | Wallet, Balance, Assets, Earnings all populated |
| QA-3018 | Earnings fetched exactly once per session | `earningsFetched.current === true` after first load |
| QA-3019 | Recent trades display correctly | Trades list renders or shows "No trades yet" |
| QA-3020 | Navigation buttons route correctly | "Open market" → Explore, "View network" → Network |
| QA-3021 | Nav rows have correct destinations | My Data, Explore, Network with descriptions |
| QA-3022 | "Register more" expands inline form | Mode switch + RegisterForm appears |

---

## Journey 3: 数据资产注册 (Data Asset Registration)

### 前置条件 (Preconditions)

- Wallet exists and has funds (for gas/registration fees)
- Entered via: Home onboarding step 3, Home veteran "Register more", or My Data page register section
- For capability registration: user switches to Capability tab

### 步骤流 (Step-by-step Flow)

#### Data Asset Path

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Expands register section / reaches step 3 | RegisterForm mounts with `mode="data"` default | `<RegisterForm />` |
| 2 | Sees Data tab active in mode switch | Tablist: "Data" (active) / "Capability" | `.home-mode-switch` |
| 3 | Drags file(s) onto dropzone | Dropzone highlights on dragover. File(s) accepted. Single file → single mode. Multiple files → bundle mode auto-detected. | `.dropzone` |
| 4 | Alternatively clicks dropzone to browse | Native file picker opens | `<input type="file">` hidden |
| 5 | File selected; form fields appear | Description textarea, rights type selector appear (progressive disclosure) | Form fields below dropzone |
| 6 | Enters description | Free text, used for search indexing | `<textarea>` |
| 7 | Selects rights type | Dropdown: Original / Co-creation / Licensed / Collection | `<select>` |
| 8 | If Co-creation: adds co-creators | Dynamic fields: address (string) + share (%) for each co-creator. Total must sum to 100. | Co-creator input rows |
| 9 | Selects price model | Radio/dropdown: Auto (bonding curve) / Fixed / Floor | Price model selector |
| 10 | Clicks "Register" button | Validates form. Sends `postFile()` or `postBundle()`. Upload progress bar appears. | `.btn-primary`, progress bar |
| 11 | Upload completes | `handleSuccess(result)` called. Toast: "Data asset registered". | Success callback |
| 12 | Sees success details | `asset_id` (masked), `file_hash` (masked), `price_model`, type shown in KV rows | Success banner |

#### Capability Path

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Clicks "Capability" tab | Mode switches to `capability`. Form changes to capability fields. | `.home-mode-tab[data-tab="capability"]` |
| 2 | Enters endpoint URL | Text input for API endpoint (https://...) | Input field |
| 3 | Enters API key | Password-type input | Input field |
| 4 | Sets rate limit | Numeric input for max calls/minute | Input field |
| 5 | Adds tags | Comma-separated tags (e.g., "nlp,translation") | Tag input |
| 6 | Clicks "Register" | `POST /api/register` with capability fields. Toast on success. | `.btn-primary` |

### 触点 (UI Touchpoints)

| Touchpoint | File | Notes |
|------------|------|-------|
| `<RegisterForm />` | `src/components/register-form.tsx` | Shared between Home and MyData |
| Dropzone (drag-drop + click) | Within RegisterForm | Progressive: shows form fields only after file selected |
| Rights type selector | Within RegisterForm | Conditional co-creator fields |
| Price model selector | Within RegisterForm | Auto/Fixed/Floor |
| Upload progress | Within RegisterForm | Shown during `postFile`/`postBundle` |

### API 调用 (API Calls)

| Action | Method | Endpoint | Body | Timeout |
|--------|--------|----------|------|---------|
| Single file register | POST | `/api/register` | FormData: `file`, `owner`, `description`, `tags`, `rights_type`, `co_creators` (JSON), `price_model`, `price` | 120s |
| Bundle register | POST | `/api/register-bundle` | FormData: `files[]`, same fields | 180s |
| Capability register | POST | `/api/register` | JSON: `{ name, endpoint, api_key, price, tags[], rate_limit }` | 30s |

### 状态变更 (State Changes)

| Signal | Change | Trigger |
|--------|--------|---------|
| `assets` | New asset appended | `loadAssets()` after success |
| `done` (local) | Set to `LaunchResult` | `handleSuccess()` callback |
| `assetCount` (derived) | Increments by 1 | `assets.value.length` recomputed |
| `isVeteran` (derived) | Becomes `true` if was `false` | First asset triggers veteran status |

### 错误分支 (Error Branches)

| Error | Trigger | User Sees | Recovery |
|-------|---------|-----------|----------|
| **Empty file** | 0-byte file selected | Client-side validation blocks submit | Select non-empty file |
| **File too large** | Exceeds server limit | Server 413 → toast error | Use smaller file |
| **Upload timeout** | Network slow, >120s (file) or >180s (bundle) | Toast: "Request timeout" | Retry with better connection |
| **Server error** | Backend registration fails | Toast: server error message. Form state preserved. | Fix server issue, retry |
| **Duplicate file** | Same hash already registered | Server returns error | Register different file or new version |
| **Invalid co-creator shares** | Shares don't sum to 100 | Client validation error | Correct share percentages |
| **Missing required fields** | Description empty | Client validation prevents submit | Fill required fields |

### 情感曲线 (Emotional Arc)

**Intent** (I want to register) → **Focus** (filling form, choosing options) → **Tension** (upload progress, waiting) → **Relief + Pride** (success, seeing asset ID)

### 验证点 (Verification Points)

| QA ID | Check | Expected |
|-------|-------|----------|
| QA-3023 | Dropzone accepts drag-drop | File selected, form fields appear |
| QA-3024 | Single vs bundle auto-detected | 1 file → POST /register, 2+ files → POST /register-bundle |
| QA-3025 | Rights type dropdown has 4 options | original, co_creation, licensed, collection |
| QA-3026 | Co-creator fields appear for co_creation | Address + share inputs render |
| QA-3027 | Price model selector works | Auto/Fixed/Floor options functional |
| QA-3028 | Upload progress shown | Progress indicator visible during upload |
| QA-3029 | Success banner shows all detail rows | asset_id, file_hash, price_model, type |
| QA-3030 | Capability tab switches form correctly | Endpoint/API key/rate limit fields appear |
| QA-3031 | POST /register returns valid asset_id | Non-empty, unique identifier |

---

## Journey 4: 市场浏览与购买 (Market Browsing & Purchase)

### 前置条件 (Preconditions)

- User has wallet and funds (balance > 0 for purchases)
- At least one asset exists on the network (registered by any user)
- User navigates to Explore page (via nav or direct route)

### 步骤流 (Step-by-step Flow)

#### Browse & Purchase Path

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Navigates to Explore | Explore page loads with 4 tabs: Browse (default), Portfolio, Stake, Bounty | `explore.tsx` with tab bar |
| 2 | Browse tab active | `ExploreBrowse` mounts. Fetches `GET /api/assets` + `GET /api/capabilities` in parallel. Loading skeleton shown. | `explore-browse.tsx` |
| 3 | Assets load | Combined list (data + capabilities) rendered. Each shows masked ID, name, tags, spot price. | Asset list |
| 4 | Types keyword in search | Debounced filter on `name`, `description`, `tags`. Results update in real-time. | `.search-box` input |
| 5 | Filters by type | Click "All" / "Data" / "Capability" toggle | `typeFilter` state: `AssetFilter` |
| 6 | Filters by tag | Click tag badge in results to filter | `tagFilter` state |
| 7 | Sorts results | Toggle between "Time" and "Value" | `sortBy` state: `SortBy` |
| 8 | Clicks an asset | Detail panel slides open. Body scroll locks. | `activeId` set, `overflow: hidden` |
| 9 | Sees tiered access (L0-L3) | `GET /api/access/quote?asset_id={id}` fetches `AccessQuoteData`. Shows each level with bond, availability, locked reasons. | Access level cards |
| 10 | Selects access level | Clicks level tab (L0/L1/L2/L3). Updates `selectedLevel`. | Level selector |
| 11 | Sees quote details | Bond amount, liability days, reputation requirement, risk level displayed. | Quote display section |
| 12 | Enters purchase amount (for equity buy) | Real-time `POST /api/quote` recalculates: `equity_minted`, `spot_price_before/after`, `price_impact`, `protocol_fee`, `burn`, `treasury`. | Amount input + live quote |
| 13 | Reviews quote | All fee components visible: 85% to creator, 7% fee, 5% burn, 3% treasury. Price impact percentage shown. | Quote breakdown |
| 14 | Clicks "Buy" | `POST /api/access/buy` with `{ asset_id, level, amount, buyer }`. Confirmation step. | `.btn-primary` |
| 15 | Purchase succeeds | Toast: success. `buyStep` advances to "success". Shows receipt. | Success state |
| 16 | Views in Portfolio | Switches to Portfolio tab or navigates to My Data | Tab switch or navigation |

#### AI Discovery Variant

| # | User Action | System Response |
|---|-------------|-----------------|
| 1 | Clicks "Smart Discover" toggle | `isDiscover` flips to true. Search input placeholder changes. |
| 2 | Types natural language intent | e.g., "I need Chinese NLP training data" |
| 3 | Submits query | `GET /api/discover?q={encoded_query}` with semantic matching |
| 4 | Matched results appear | `discoverResults` populated, displayed in same list format |

#### Preview Variant

| # | User Action | System Response |
|---|-------------|-----------------|
| 1 | Clicks "Preview" on an asset | `previewId` set. `<DataPreview />` overlay opens. |
| 2 | Sees file content | Markdown/JSON/CSV/image rendered in read-only viewer |
| 3 | Presses Escape | `useEscapeKey()` closes preview overlay |

#### Capability Invoke Variant

| # | User Action | System Response |
|---|-------------|-----------------|
| 1 | Opens a capability-type asset | Detail panel shows invoke section instead of equity buy |
| 2 | Enters JSON input | Default: `{"text": "hello"}`. Textarea for custom JSON. |
| 3 | Clicks "Invoke" | `POST /api/capability/invoke` with `{ capability_id, input }` |
| 4 | Sees JSON output | `invokeResult` displayed in formatted JSON block |

### 触点 (UI Touchpoints)

| Touchpoint | File | Notes |
|------------|------|-------|
| Tab bar (Browse/Portfolio/Stake/Bounty) | `explore.tsx` | `role="tablist"` with ARIA |
| Search box | `explore-browse.tsx` | Debounced, real-time filtering |
| Type filter toggles | `explore-browse.tsx` | All/Data/Capability |
| Tag filter badges | `explore-browse.tsx` | Click to filter |
| Sort toggle | `explore-browse.tsx` | Time/Value |
| Asset list | `explore-browse.tsx` | Masked IDs, prices, tags |
| Detail panel (slide-in) | `explore-browse.tsx` | Body scroll lock, Escape to close |
| Access level cards (L0-L3) | `explore-browse.tsx` | Bond, availability, locked reasons |
| Quote breakdown | `explore-browse.tsx` | Live fee calculation |
| `<DataPreview />` overlay | `src/components/data-preview.tsx` | File content viewer |
| Invoke section | `explore-browse.tsx` | JSON input/output for capabilities |

### API 调用 (API Calls)

| Action | Method | Endpoint | Notes |
|--------|--------|----------|-------|
| Load assets | GET | `/api/assets` | Data assets |
| Load capabilities | GET | `/api/capabilities` | Service capabilities |
| Access quote | GET | `/api/access/quote?asset_id={id}` | Returns `AccessQuoteData` with all levels |
| Equity quote | POST | `/api/quote` | `{ asset_id, amount_oas }` → `QuoteResult` |
| Purchase access | POST | `/api/access/buy` | `{ asset_id, level, amount, buyer }` → `BuyResult` |
| Smart discover | GET | `/api/discover?q={query}` | Semantic search |
| Invoke capability | POST | `/api/capability/invoke` | `{ capability_id, input }` |

### 状态变更 (State Changes)

| State | Change | Trigger |
|-------|--------|---------|
| `allAssets` (local) | Populated with data + capability assets | Initial fetch |
| `activeId` (local) | Set to clicked asset ID | Asset click |
| `accessQuote` (local) | `AccessQuoteData` loaded | Detail panel open |
| `buyStep` (local) | `form` → `quoted` → `success` | Quote → Buy flow |
| `balance` (global) | Decreases by purchase amount | After successful buy |
| `discoverResults` (local) | Populated from discover API | Smart discover query |

### 错误分支 (Error Branches)

| Error | Trigger | User Sees | Recovery |
|-------|---------|-----------|----------|
| **Insufficient balance** | `amount > balance` | Quote shows warning; buy button disabled or error toast | Add funds (PoW register, receive from trade) |
| **Slippage too high** | `price_impact` exceeds threshold | Warning in quote display | Reduce purchase amount |
| **Asset not found** | Deep link to deleted/delisted asset | Toast: "Not found". Panel closes. | Browse for other assets |
| **Reputation too low** | User reputation below level requirement | Level card shows "locked" with reason `reputation_too_low` | Build reputation through successful trades |
| **Invoke failure** | Capability endpoint down | Error response in JSON output section | Retry or contact capability provider |
| **Assets load fails** | Network error on initial fetch | Empty state component shown | Refresh page |

### 情感曲线 (Emotional Arc)

**Exploration** (browsing, discovering) → **Interest** (clicking asset, reading details) → **Calculation** (reviewing quote, understanding fees) → **Decision** (commit to buy) → **Confirmation** (purchase complete, asset in portfolio)

### 验证点 (Verification Points)

| QA ID | Check | Expected |
|-------|-------|----------|
| QA-3032 | Explore page loads with 4 tabs | Browse, Portfolio, Stake, Bounty tabs visible |
| QA-3033 | Assets + capabilities load in parallel | Both data and capability assets in list |
| QA-3034 | Search filters results in real-time | Typing filters list; debounce prevents excessive re-renders |
| QA-3035 | Type filter works | All/Data/Capability toggles filter correctly |
| QA-3036 | Detail panel opens with body scroll lock | `overflow: hidden` on body, panel visible |
| QA-3037 | Access levels (L0-L3) display with quotes | Each level shows bond, availability, locked reason if applicable |
| QA-3038 | Live quote updates on amount change | Fee breakdown recalculates in real-time |
| QA-3039 | Purchase flow completes | `POST /access/buy` succeeds, toast shown, buyStep = success |
| QA-3040 | Escape closes detail panel | `useEscapeKey()` resets `activeId` |
| QA-3041 | Smart Discover returns semantic matches | `/api/discover` endpoint returns relevant results |
| QA-3042 | Capability invoke shows JSON output | Input submitted, output rendered |
| QA-3043 | DataPreview overlay renders file content | Markdown/JSON/CSV/image displayed correctly |

---

## Journey 5: 资产管理 (Asset Management)

### 前置条件 (Preconditions)

- User has registered at least one asset
- User navigates to My Data page

### 步骤流 (Step-by-step Flow)

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Navigates to My Data | `MyData` component mounts. `loadAssets()` fetches asset list. Two tabs: Data / Capabilities. | `mydata.tsx` |
| 2 | Sees asset list | Assets displayed with masked ID, name, tags, status, spot price. Search box + sort + tag filter above. | Asset list section |
| 3 | Searches by keyword | `q` state filters assets by name/description/tags | `.search-box` |
| 4 | Sorts by time or value | `sortBy` toggles between `time` and `value` | Sort toggle |
| 5 | Filters by tag | Clicks tag badge to set `tagFilter` | Tag badges |
| 6 | Clicks/expands an asset | `expanded` set to asset ID. Detail section shows: full ID (masked), description, tags, status, price, rights type, co-creators, hash status. | Expandable row |
| 7 | Views asset details | All metadata visible. Actions row appears. | Detail section within expanded row |

#### Edit Tags Flow

| # | User Action | System Response |
|---|-------------|-----------------|
| 8a | Clicks "Edit Tags" | `editTagsTarget` set. Inline tag editor appears with current tags. |
| 9a | Modifies tags (comma-separated) | `editTagsValue` updates |
| 10a | Clicks "Save" | `POST /api/asset/{id}/tags` with new tags. Toast on success. `loadAssets()` refresh. |

#### Re-register (Version Bump) Flow

| # | User Action | System Response |
|---|-------------|-----------------|
| 8b | Clicks "Re-register" | `reregistering` set to asset ID. Inline RegisterForm appears (pre-filled). |
| 9b | Uploads new file version | Same registration form flow |
| 10b | Submits | `POST /api/re-register` (or `add_asset_version`). New version linked to original. Toast on success. |

#### Delete Flow

| # | User Action | System Response |
|---|-------------|-----------------|
| 8c | Clicks "Delete" | `confirmDel` set to asset ID. Confirmation dialog appears with warning text. |
| 9c | Clicks "Confirm Delete" | `deleteAsset(id)` → `DELETE /api/asset/{id}`. Toast on success. Asset removed from list. |
| 10c | Or clicks "Cancel" | Dialog dismisses. `confirmDel` reset to null. |

#### Dispute Flow

| # | User Action | System Response |
|---|-------------|-----------------|
| 8d | Clicks "Dispute" | `disputeTarget` set. Reason input field appears. |
| 9d | Enters dispute reason | `disputeReason` updates |
| 10d | Clicks "Submit Dispute" | `POST /api/asset/{id}/dispute` with `{ reason }`. `disputing` loading state. Toast on success. Asset shows disputed badge. |

#### Version History Flow

| # | User Action | System Response |
|---|-------------|-----------------|
| 8e | Clicks "Versions" | `versionsTarget` set. `GET /api/asset/{id}/versions` fetches version list. |
| 9e | Sees version timeline | List of versions with version number + timestamp. |

#### Lifecycle Management Flow

| # | User Action | System Response |
|---|-------------|-----------------|
| 8f | Clicks "Shutdown" (if asset owner) | `shutdownConfirm` set. Warning dialog explains implications (no new buys, limited sells). |
| 9f | Confirms shutdown | `POST /api/asset/{id}/shutdown`. Status changes to `SHUTDOWN_PENDING`. |

### 触点 (UI Touchpoints)

| Touchpoint | File | Notes |
|------------|------|-------|
| Tab bar (Data / Capabilities) | `mydata.tsx` | `activeTab` state |
| Search + Sort + Tag filter | `mydata.tsx` | Filter controls above list |
| Asset list with expandable rows | `mydata.tsx` | Click to expand/collapse |
| Inline tag editor | `mydata.tsx` | Edit tags without leaving page |
| Inline RegisterForm | `src/components/register-form.tsx` | For re-registration |
| Delete confirmation dialog | `mydata.tsx` | Destructive action guard |
| Dispute form | `mydata.tsx` | Reason input + submit |
| Version history | `mydata.tsx` | Timeline display |
| `<EmptyState />` | `src/components/empty-state.tsx` | When no assets |
| Owner earnings section | `mydata.tsx` | `ownerEarnings` display |
| Capabilities tab | `mydata.tsx` | Delivery endpoints + earnings |

### API 调用 (API Calls)

| Action | Method | Endpoint |
|--------|--------|----------|
| Load assets | GET | `/api/assets` |
| Delete asset | DELETE | `/api/asset/{id}` |
| Edit tags | POST | `/api/asset/{id}/tags` |
| Re-register | POST | `/api/re-register` |
| File dispute | POST | `/api/asset/{id}/dispute` |
| Version history | GET | `/api/asset/{id}/versions` |
| Lifecycle shutdown | POST | `/api/asset/{id}/shutdown` |
| Load capabilities | GET | `/api/capabilities` |
| Capability earnings | GET | `/api/capability/earnings?provider={addr}` |

### 状态变更 (State Changes)

| Signal/State | Change | Trigger |
|-------------|--------|---------|
| `assets` (global) | Refreshed after mutation | `loadAssets()` after edit/delete/register |
| `expanded` (local) | Set to asset ID or null | Expand/collapse click |
| `confirmDel` (local) | Set to ID for delete confirmation | Delete button click |
| `disputeTarget` (local) | Set to ID for dispute form | Dispute button click |
| `reregistering` (local) | Set to ID for inline register | Re-register button click |
| `editTagsTarget` (local) | Set to ID for tag editing | Edit tags button click |

### 错误分支 (Error Branches)

| Error | Trigger | User Sees | Recovery |
|-------|---------|-----------|----------|
| **Delete fails** | Server error | Toast: error message. Asset remains. | Retry |
| **Tag update fails** | Invalid tags or server error | Toast: error. Original tags preserved. | Correct tags, retry |
| **Dispute submit fails** | Network error | Toast: error. Form preserved. | Retry |
| **Version fetch fails** | Asset has no versions | Empty version list | Normal; asset has single version |
| **Shutdown fails** | Not asset owner | Toast: unauthorized error | Only owner can shutdown |

### 情感曲线 (Emotional Arc)

**Control** (reviewing owned assets) → **Maintenance** (editing, organizing) → **Confidence** (managing disputes, versioning) → **Satisfaction** (organized portfolio)

### 验证点 (Verification Points)

| QA ID | Check | Expected |
|-------|-------|----------|
| QA-3044 | My Data loads asset list | `loadAssets()` returns list; rendered with masked IDs |
| QA-3045 | Search filters assets | Typing reduces visible list |
| QA-3046 | Sort by time/value works | List reorders correctly |
| QA-3047 | Expand shows full asset details | Metadata, tags, status, actions visible |
| QA-3048 | Delete flow requires confirmation | Confirm dialog appears before DELETE call |
| QA-3049 | DELETE /asset/{id} removes asset | Asset disappears from list, toast shown |
| QA-3050 | Edit tags saves successfully | POST /asset/{id}/tags succeeds, tags update |
| QA-3051 | Dispute form submits | POST with reason, disputed badge appears |
| QA-3052 | Version history loads | Version list with timestamps displayed |
| QA-3053 | Empty state shown when no assets | `<EmptyState />` component renders |

---

## Journey 6: 自动化配置 (Automation Setup)

### 前置条件 (Preconditions)

- User has wallet (for registration actions)
- User navigates to Automation page
- Backend scanning service available (DataVault integrated)

### 步骤流 (Step-by-step Flow)

#### Queue Tab (Task Inbox)

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Opens Automation page | Two tabs: Queue (default) / Rules. `loadInbox()` + `loadTrust()` on mount. | `automation.tsx` |
| 2 | Sees pending inbox items | Each item shows: `suggested_name`, `suggested_tags`, `sensitivity` (safe/moderate/sensitive), `confidence` (0-1), `status` (pending). | Inbox list |
| 3 | Reviews an item | Reads name, tags, sensitivity badge, confidence percentage | Item row |
| 4a | Clicks "Approve" on one item | `approveItem(id)` → optimistic update (status → approved) + `POST /api/inbox/{id}/approve` | Approve button |
| 4b | Clicks "Reject" on one item | `rejectItem(id)` → optimistic update (status → rejected) + `POST /api/inbox/{id}/reject` | Reject button |
| 4c | Clicks "Edit" on one item | `editingId` set. Inline edit fields appear for name, tags, description. | Edit form |
| 5c | Modifies fields and saves | `editItem(id, updates)` → `POST /api/inbox/{id}/edit` with `{ name, tags, description }` | Save button |
| 6 | Clicks "Approve All" | `approveAll()` → all pending items set to approved (single signal write + parallel HTTP) | Bulk action button |
| 7 | Clicks "Reject All" | `rejectAll()` → all pending items set to rejected | Bulk action button |

#### Scan Flow

| # | User Action | System Response |
|---|-------------|-----------------|
| 1 | Enters directory path | `scanPath` state updates (default: `~/Documents`) |
| 2 | Clicks "Scan" | `scanDirectory(path)` → `POST /api/scan` with `{ path }`. `scanning` signal = true. |
| 3 | Scan completes | `lastScan` updated with `{ scanned, added }`. `loadInbox()` refreshes items. New items appear in queue. |

#### Rules Tab (Agent Configuration)

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Switches to Rules tab | Rules configuration panel renders | `tab === 'rules'` |
| 2 | Sets trust level | Three options: 0 = Manual (I), 1 = Semi-auto (II), 2 = Full-auto (III). `setTrust(level)` → `POST /api/inbox/trust`. | Trust level selector |
| 3 | Sets confidence threshold | Three tiers: Strict (90%), Balanced (70%), Permissive (50%) | Threshold selector |
| 4 | Configures agent scheduler | Fields: interval_hours, scan_paths, auto_register, auto_trade, trade_max_spend | Agent config form |
| 5 | Saves agent config | `POST /api/agent/config` with full config object. `setSavingCfg(true)`. | Save button |
| 6 | Enables agent scheduler | `POST /api/agent/start`. Status indicator changes to "Running". | Enable toggle |
| 7 | Triggers manual run | `POST /api/agent/run`. `runningNow` = true. Waits for completion. | "Run now" button |
| 8 | Views run history | `GET /api/agent/history` → list of `HistoryRun` with timestamp, counts, errors, duration | History section |

### 触点 (UI Touchpoints)

| Touchpoint | File | Notes |
|------------|------|-------|
| Tab bar (Queue / Rules) | `automation.tsx` | Two primary sections |
| Inbox item list | `automation.tsx` | Per-item: approve/reject/edit |
| Bulk action buttons | `automation.tsx` | Approve All / Reject All |
| Inline edit form | `automation.tsx` | Name, tags, description editing |
| Scan path input + button | `automation.tsx` | Directory path + scan trigger |
| Trust level selector | `automation.tsx` | 3 levels: I/II/III with icons |
| Confidence threshold | `automation.tsx` | 3 tiers with i18n keys |
| Agent config form | `automation.tsx` | Interval, paths, auto flags, max spend |
| Agent status indicator | `automation.tsx` | Running/stopped + stats |
| Run history list | `automation.tsx` | Timestamped run records |
| `<EmptyState />` | `src/components/empty-state.tsx` | When inbox is empty |
| `<Section />` | `src/components/section.tsx` | Collapsible sections |

### API 调用 (API Calls)

| Action | Method | Endpoint | Body |
|--------|--------|----------|------|
| Load inbox | GET | `/api/inbox` | - |
| Load trust config | GET | `/api/inbox/trust` | - |
| Approve item | POST | `/api/inbox/{id}/approve` | `{}` |
| Reject item | POST | `/api/inbox/{id}/reject` | `{}` |
| Edit item | POST | `/api/inbox/{id}/edit` | `{ name, tags, description }` |
| Set trust level | POST | `/api/inbox/trust` | `{ trust_level, auto_threshold }` |
| Scan directory | POST | `/api/scan` | `{ path }` |
| Get agent config | GET | `/api/agent/config` | - |
| Save agent config | POST | `/api/agent/config` | `{ enabled, interval_hours, scan_paths, auto_register, auto_trade, trade_max_spend }` |
| Start agent | POST | `/api/agent/start` | `{}` |
| Stop agent | POST | `/api/agent/stop` | `{}` |
| Trigger run | POST | `/api/agent/run` | `{}` |
| Get run history | GET | `/api/agent/history` | - |
| Get agent status | GET | `/api/agent/status` | - |

### 状态变更 (State Changes)

| Signal/State | Change | Trigger |
|-------------|--------|---------|
| `inboxItems` (global) | Updated with inbox data | `loadInbox()` |
| `trustConfig` (global) | Updated with trust settings | `loadTrust()` |
| `scanning` (global) | `true` during scan, `false` after | `scanDirectory()` |
| `lastScan` (global) | Set to `{ scanned, added }` | Scan completion |
| `agentStatus` (local) | Agent running state | `GET /agent/status` |
| `agentConfig` (local) | Config fields | `GET /agent/config` |
| `agentHistory` (local) | Run history list | `GET /agent/history` |

### 错误分支 (Error Branches)

| Error | Trigger | User Sees | Recovery |
|-------|---------|-----------|----------|
| **Scan path not found** | Invalid directory path | Scan returns error; toast message | Enter valid path |
| **Scan timeout** | Very large directory | Toast: timeout error | Scan smaller subdirectory |
| **Approve fails server-side** | Item no longer exists | Optimistic update reverts on next `loadInbox()` | Refresh inbox |
| **Agent config save fails** | Invalid config values | Toast: error | Correct values, retry |
| **Agent run fails** | Scan/register errors during cycle | `agentStatus.last_result` shows error. `total_errors` increments. | Check history for details |
| **Empty inbox** | No pending items | `<EmptyState />` with prompt to scan | Trigger a directory scan |

### 情感曲线 (Emotional Arc)

**Awareness** (seeing what was scanned) → **Judgment** (reviewing, approving/rejecting) → **Trust** (configuring automation levels) → **Delegation** (agent runs autonomously)

### 验证点 (Verification Points)

| QA ID | Check | Expected |
|-------|-------|----------|
| QA-3054 | Inbox loads pending items | `inboxItems` populated with `status: pending` items |
| QA-3055 | Approve updates item status | Optimistic: immediate UI update. Server: POST succeeds. |
| QA-3056 | Reject updates item status | Same optimistic pattern as approve |
| QA-3057 | Approve All processes all pending | All pending items → approved in single signal write |
| QA-3058 | Edit inline saves changes | POST /inbox/{id}/edit with updated fields |
| QA-3059 | Scan directory returns results | `lastScan` shows scanned + added counts |
| QA-3060 | Trust level saves | POST /inbox/trust persists setting |
| QA-3061 | Confidence threshold saves | Included in trust config POST |
| QA-3062 | Agent config save round-trips | Save → reload → same values |
| QA-3063 | Agent manual run completes | POST /agent/run returns, history updates |
| QA-3064 | Run history displays correctly | Timestamped entries with counts and duration |

---

## Journey 7: 网络配置 (Network Configuration)

### 前置条件 (Preconditions)

- User has wallet (identity exists)
- User navigates to Network page
- Backend services running (identity, AI config, chain client)

### 步骤流 (Step-by-step Flow)

#### Node Identity & AI Config

| # | User Action | System Response | Component |
|---|-------------|-----------------|-----------|
| 1 | Opens Network page | Multiple collapsible `<Section>` components load. Identity + node role fetched. | `network.tsx` |
| 2 | Views node identity | Public key (masked by default), node ID, roles, chain height, peers count | Identity section |
| 3 | Toggles public key visibility | `showPubkey` state flips. Full key shown/hidden. | Toggle button |
| 4 | Configures AI provider | Dropdown: Claude / OpenAI / Ollama / Custom. `apiProvider` state. | Provider selector |
| 5 | Enters API key | Password-type input. `apiKey` state. Toggle visibility via `showApiKey`. | API key input |
| 6 | Enters custom endpoint (if custom) | `apiEndpoint` state | Endpoint input |
| 7 | Clicks "Save" | `POST /api/node/ai-config` with `{ provider, api_key, endpoint }`. Status indicator updates. | Save button |

#### Role Registration

| # | User Action | System Response |
|---|-------------|-----------------|
| 8 | Clicks "Become Validator" | `rolePanel` set to `validator`. Stake amount input appears. |
| 9 | Enters stake amount | Must meet minimum (MAINNET: 10,000 OAS, TESTNET: 100 OAS) |
| 10 | Confirms | `POST /api/node/role/validator` with `{ stake }`. Role added to `nodeRole.roles`. |
| 11 | Or clicks "Become Arbitrator" | `rolePanel` set to `arbitrator`. Specialization tags input appears. |
| 12 | Enters tags | Comma-separated specialization areas |
| 13 | Confirms | `POST /api/node/role/arbitrator` with `{ tags }`. |

#### Sub-sections (Collapsible)

Each renders as a `<Section>` component that can be expanded/collapsed:

| Section | Component | Key Actions |
|---------|-----------|-------------|
| **Watermark Tool** | `<WatermarkSection />` | Three tabs: Embed (file + caller → fingerprinted file), Extract (file → fingerprint hex), Trace (fingerprint → distribution records) |
| **Fingerprints** | `<FingerprintsSection />` | View distribution records, filter by asset |
| **Governance** | `<GovernanceSection />` | View proposals, cast votes (yes/no/abstain), see vote tallies |
| **Contribution Stats** | `<ContributionSection />` | View proof-of-contribution scores, verify certificates |
| **Cache Management** | `<CacheSection />` | View cache stats, purge cache |
| **Leakage Detection** | `<LeakageSection />` | Check leakage budgets, reset leakage counters |
| **Feedback** | `<FeedbackSection />` | Submit bug reports, suggestions, feedback |

#### Consensus & Staking (Chain Section)

| # | User Action | System Response |
|---|-------------|-----------------|
| 1 | Views consensus status | `ConsensusStatus`: epoch, slot, active validators, total staked |
| 2 | Clicks "Delegate" | `csAction` set to `delegate`. Validator ID + amount inputs appear. |
| 3 | Enters validator + amount | `csValidatorId` + `csAmount` states |
| 4 | Confirms delegation | POST to chain staking endpoint. Loading state → confirmation. |

### 触点 (UI Touchpoints)

| Touchpoint | File | Notes |
|------------|------|-------|
| Node identity card | `network.tsx` | Masked pubkey, toggle visibility |
| AI provider config | `network.tsx` | Dropdown + API key + endpoint |
| Role registration panels | `network.tsx` | Validator (stake) / Arbitrator (tags) |
| `<WatermarkSection />` | `src/components/network/watermark.tsx` | Embed / Extract / Trace tabs |
| `<FingerprintsSection />` | `src/components/network/fingerprints.tsx` | Distribution records |
| `<GovernanceSection />` | `src/components/network/governance.tsx` | Proposals + voting |
| `<ContributionSection />` | `src/components/network/contribution.tsx` | Proof-of-contribution stats |
| `<CacheSection />` | `src/components/network/cache.tsx` | Cache management |
| `<LeakageSection />` | `src/components/network/leakage.tsx` | Leakage budget tracking |
| `<FeedbackSection />` | `src/components/network/feedback.tsx` | User feedback submission |
| `<Section />` wrapper | `src/components/section.tsx` | Collapsible sections for reduced overload |
| Consensus status | `network.tsx` | Chain state display |
| Chain validators list | `src/api/chain.ts` via `useChain` hook | Validator data from chain |

### API 调用 (API Calls)

| Action | Method | Endpoint |
|--------|--------|----------|
| Load identity | GET | `/api/identity` |
| Load node role | GET | `/api/node/role` |
| Save AI config | POST | `/api/node/ai-config` |
| Register as validator | POST | `/api/node/role/validator` |
| Register as arbitrator | POST | `/api/node/role/arbitrator` |
| Embed watermark | POST | `/api/fingerprint/embed` |
| Extract watermark | POST | `/api/fingerprint/extract` |
| Trace fingerprint | GET | `/api/fingerprints` |
| Get proposals | GET | `/api/governance/proposals` |
| Cast vote | POST | `/api/governance/vote` |
| Get contribution stats | GET | `/api/contribution/stats` |
| Cache stats | GET | `/api/cache/stats` |
| Purge cache | POST | `/api/cache/purge` |
| Check leakage | GET | `/api/leakage/check` |
| Reset leakage | POST | `/api/leakage/reset` |
| Submit feedback | POST | `/api/feedback` |
| Chain validators | GET | Chain REST API via `getValidators()` |
| Consensus status | GET | Chain REST API via `useChain()` |
| Delegate stake | POST | Chain tx endpoint |

### 状态变更 (State Changes)

| State | Change | Trigger |
|-------|--------|---------|
| `nodeIdentity` (local) | Node info loaded | Initial fetch |
| `nodeRole` (local) | Roles, stake, tags loaded | Initial fetch |
| `apiProvider` (local) | Selected provider | User selection |
| `rolePanel` (local) | `null` → `validator` or `arbitrator` | Role button click |
| `consensus` (local) | Chain consensus data | Chain query |
| `identity` (global) | Refreshed if wallet changed | `loadIdentity()` |

### 错误分支 (Error Branches)

| Error | Trigger | User Sees | Recovery |
|-------|---------|-----------|----------|
| **Invalid API key** | Wrong key for provider | Save succeeds but status shows "invalid" | Enter correct key |
| **Insufficient stake** | Below minimum for validator | Toast: error with minimum requirement | Accumulate more OAS |
| **Chain not connected** | No running chain node | Consensus section shows offline state. Staking disabled. | Start chain node or switch to standalone |
| **Watermark embed fails** | Unsupported file type | Toast: error message | Use supported file type |
| **Governance vote fails** | Already voted or voting period ended | Toast: specific error | Check proposal status |

### 情感曲线 (Emotional Arc)

**Orientation** (understanding node identity) → **Configuration** (setting up AI provider) → **Commitment** (staking, choosing roles) → **Ownership** (managing network participation)

### 验证点 (Verification Points)

| QA ID | Check | Expected |
|-------|-------|----------|
| QA-3065 | Node identity displays | Masked pubkey, node ID visible |
| QA-3066 | Public key toggle works | Full key shown/hidden on click |
| QA-3067 | AI provider config saves | POST succeeds, status indicator updates |
| QA-3068 | Validator registration works | POST /node/role/validator with stake succeeds |
| QA-3069 | Arbitrator registration works | POST /node/role/arbitrator with tags succeeds |
| QA-3070 | Watermark embed/extract cycle | Embed → Extract returns original fingerprint |
| QA-3071 | Governance proposals load | List of proposals with vote counts |
| QA-3072 | Vote submission works | POST /governance/vote succeeds |
| QA-3073 | Collapsible sections toggle | Each `<Section>` expands/collapses correctly |
| QA-3074 | Feedback submission works | POST /feedback succeeds, toast shown |
| QA-3075 | Cache purge works | POST /cache/purge succeeds |
| QA-3076 | Consensus status displays (when chain connected) | Epoch, slot, validators shown |

---

## Journey 8: 跨页面流 (Cross-Page Flows)

### 前置条件 (Preconditions)

- User has completed onboarding (wallet + funds + at least one asset)
- Multiple features have been used across different pages
- Notification system active

### Flow A: 注册到收益 (Register → Earn)

```
Register asset (Home/MyData)
    │
    ▼
View in My Data ───→ Asset appears in list with asset_id
    │
    ▼
Listed on Market ───→ Visible in Explore Browse tab (auto-indexed)
    │
    ▼
Another user buys ──→ Transaction recorded; buyer gets equity
    │
    ▼
See earnings on Home ─→ Veteran view: earnings total + recent trade entry
```

**步骤流:**

| # | Page | Action | System Response |
|---|------|--------|-----------------|
| 1 | Home | Register data asset via onboarding or inline form | `POST /api/register` → asset_id returned |
| 2 | My Data | Click "View My Data" or navigate | Asset visible in list. Tags, status, price model shown. |
| 3 | Explore (other user) | Other user searches, finds asset | Asset appears in browse results |
| 4 | Explore (other user) | Other user purchases access | `POST /api/access/buy` → equity transferred, bond paid |
| 5 | Home | Original owner returns | Earnings updated: `GET /api/earnings?owner={addr}` shows new transaction |
| 6 | Home | Reviews earnings section | `total_earned` increased. Trade entry with buyer address + amount visible. |

**API 调用链:**
```
POST /register → GET /assets (My Data) → GET /assets (Explore, other user)
→ POST /access/buy (other user) → GET /earnings (original owner, Home)
```

**状态流:**
```
assets.value: [] → [asset] (register)
balance.value: X → X+earned (after someone buys)
ownerEarnings: null → { total_earned: Y, transactions: [...] }
```

### Flow B: 发现到持仓 (Discovery → Portfolio)

```
Explore (Browse/Discover)
    │
    ▼
Find asset ───→ View details in slide panel
    │
    ▼
Buy access ───→ POST /access/buy succeeds
    │
    ▼
View in Portfolio ─→ Explore Portfolio tab: owned shares, avg price, current value
    │
    ▼
Check earnings ───→ Home: earnings reflect purchases if owning revenue-generating assets
```

**步骤流:**

| # | Page | Action | System Response |
|---|------|--------|-----------------|
| 1 | Explore (Browse) | Search or discover assets | Results displayed |
| 2 | Explore (Browse) | Click asset, review L0-L3 levels | Access quote loaded |
| 3 | Explore (Browse) | Purchase L1 access | `POST /access/buy`. buyStep → success. |
| 4 | Explore (Portfolio) | Switch to Portfolio tab | Owned shares listed with amounts + current value |
| 5 | Home | Navigate home | Earnings section includes any revenue from owned positions |

### Flow C: 自动扫描到注册 (Scan → Register)

```
Automation (Queue tab)
    │
    ▼
Enter scan path ───→ POST /scan
    │
    ▼
Scan results in Inbox ─→ New items with suggested_name, tags, sensitivity, confidence
    │
    ▼
Review + Approve ───→ Items move to approved status
    │
    ▼
View in My Data ───→ Approved items appear as registered assets
```

**步骤流:**

| # | Page | Action | System Response |
|---|------|--------|-----------------|
| 1 | Automation | Enter directory path (e.g., `~/Documents`) | `scanPath` updated |
| 2 | Automation | Click "Scan" | `POST /api/scan`. Progress shown. |
| 3 | Automation | Scan completes | `lastScan` shows counts. New inbox items appear. |
| 4 | Automation | Review items: check name, tags, sensitivity | Read metadata per item |
| 5 | Automation | Approve individual or all | Optimistic update + parallel HTTP POSTs |
| 6 | My Data | Navigate to My Data | Newly registered assets visible in list |

### Flow D: 通知驱动导航 (Notification-driven Navigation)

```
Notification arrives
    │
    ▼
Bell icon shows unread count ───→ unreadCount signal > 0
    │
    ▼
Click notification ───→ markNotificationsRead(id)
    │
    ▼
Navigate to relevant page ───→ e.g., dispute → My Data, purchase → Explore
```

**步骤流:**

| # | Component | Action | System Response |
|---|-----------|--------|-----------------|
| 1 | Nav bell | Backend emits event (purchase, dispute, etc.) | `loadNotifications()` via polling or page load |
| 2 | Nav bell | Badge shows unread count | `unreadCount.value > 0` |
| 3 | Notification panel | User clicks notification | `markNotificationsRead(id)` → `POST /api/notifications/read` |
| 4 | Router | Redirect based on `event_type` | `purchase` → Explore/Portfolio, `dispute` → My Data, `earnings` → Home |

### 触点 (UI Touchpoints -- Cross-page)

| Touchpoint | Pages | Notes |
|------------|-------|-------|
| Toast notifications | All pages | Success/error feedback spans entire app |
| Nav bar (5 tabs) | All pages | `src/components/nav.tsx` -- consistent navigation |
| Theme toggle | All pages | ☀/☾ in nav, persisted via localStorage |
| Language toggle | All pages | zh/en in nav, drives all i18n signals |
| Notification bell | All pages (nav) | `unreadCount` badge, notification panel |
| `assets` global signal | Home, MyData, Explore | Shared asset state |
| `balance` global signal | Home, Explore (for purchase validation) | Shared balance state |
| `identity` global signal | Home, MyData, Network | Shared wallet state |

### API 调用 (Cross-page API Flow)

```
                           ┌─ GET /assets ───────── Home (veteran count)
                           │                        MyData (asset list)
                           │                        Explore (browse list)
                           │
GET /identity ─────────────┤
GET /balance ──────────────┤
                           │
                           ├─ GET /earnings ─────── Home (veteran earnings)
                           │                        MyData (owner earnings)
                           │
                           ├─ GET /inbox ─────────── Automation (queue)
                           │
                           ├─ GET /notifications ── Nav (bell badge)
                           │
                           └─ GET /capabilities ─── Explore (browse)
                                                    MyData (capabilities tab)
```

### 状态变更 (Cross-page State Consistency)

| Signal | Written By | Read By |
|--------|-----------|---------|
| `identity` | `loadIdentity()` (app init, Home) | Home, MyData, Network, Nav |
| `balance` | `loadBalance()` (app init, Home, after transactions) | Home, Explore (buy validation) |
| `assets` | `loadAssets()` (Home, MyData, after register/delete) | Home (count), MyData (list) |
| `theme` | Nav toggle | All pages (CSS `data-theme`) |
| `lang` | Nav toggle | All pages (i18n computed signal) |
| `notifications` | `loadNotifications()` | Nav bell |
| `inboxItems` | `loadInbox()` | Automation queue |
| `trustConfig` | `loadTrust()` | Automation rules |

### 错误分支 (Error Branches -- Cross-page)

| Error | Trigger | Impact | Recovery |
|-------|---------|--------|----------|
| **Backend restart** | Server process restart | All API calls fail temporarily. Toasts: "Network error". | Wait for restart. Refresh page. |
| **Token expiry** | Auth token invalidated | 401 errors. `ensureToken()` retries. | Token auto-refreshes on next request via `ensureToken()` |
| **Stale data after navigation** | Signal not refreshed after cross-page action | Asset count mismatch between pages | Each page calls `loadAssets()` on mount |
| **Notification routing fails** | Unknown event_type | Notification panel shows but no navigation | Manual navigation via nav bar |

### 情感曲线 (Emotional Arc)

**Flow A:** Accomplishment (register) → Anticipation (waiting for buyers) → Delight (seeing earnings)

**Flow B:** Curiosity (discovery) → Decision (purchasing) → Ownership (portfolio view)

**Flow C:** Efficiency (automated scan) → Control (review/approve) → Growth (more assets)

**Flow D:** Alertness (notification) → Action (click-through) → Resolution (handle event)

### 验证点 (Verification Points)

| QA ID | Check | Expected |
|-------|-------|----------|
| QA-3077 | Registered asset appears in My Data | Navigate Home → register → MyData → asset in list |
| QA-3078 | Registered asset appears in Explore | Other session can find asset via browse/search |
| QA-3079 | Earnings update after purchase | Owner's Home shows new transaction in earnings |
| QA-3080 | Purchased asset in Portfolio | Buyer's Explore Portfolio tab shows owned shares |
| QA-3081 | Scanned items flow to My Data | Scan → approve → asset visible in My Data |
| QA-3082 | Notification navigation works | Click notification → correct page opens |
| QA-3083 | Balance consistent across pages | Home balance matches Explore buy validation |
| QA-3084 | Theme persists across navigation | Toggle theme → navigate → theme preserved |
| QA-3085 | Language persists across navigation | Toggle language → navigate → language preserved |
| QA-3086 | Assets signal consistent | Home asset count matches My Data list length |

---

## 附录 A: QA ID 索引 (QA-3000 Series)

| Range | Journey | Count |
|-------|---------|-------|
| QA-3001 -- QA-3015 | J1: New User Onboarding | 15 |
| QA-3016 -- QA-3022 | J2: Veteran Return Visit | 7 |
| QA-3023 -- QA-3031 | J3: Data Asset Registration | 9 |
| QA-3032 -- QA-3043 | J4: Market Browsing & Purchase | 12 |
| QA-3044 -- QA-3053 | J5: Asset Management | 10 |
| QA-3054 -- QA-3064 | J6: Automation Setup | 11 |
| QA-3065 -- QA-3076 | J7: Network Configuration | 12 |
| QA-3077 -- QA-3086 | J8: Cross-Page Flows | 10 |
| **Total** | | **86** |

---

## 附录 B: 信号依赖图 (Signal Dependency Map)

```
identity (store/ui.ts)
    ├──→ walletExists (home.tsx derived)
    ├──→ walletAddr (home.tsx derived)
    └──→ walletAddress() (store/ui.ts helper)
            ├──→ earnings fetch guard
            └──→ notifications fetch

balance (store/ui.ts)
    └──→ hasStarterFunds (home.tsx derived)
            └──→ currentStep (home.tsx derived)
                    └──→ isVeteran (home.tsx derived)

assets (store/assets.ts)
    └──→ assetCount (home.tsx derived)
            └──→ isVeteran (home.tsx derived)

theme (store/ui.ts) → CSS data-theme attribute
lang (store/ui.ts) → i18n computed → all components

inboxItems (store/scanner.ts) → Automation queue
trustConfig (store/scanner.ts) → Automation rules
scanning (store/scanner.ts) → Scan loading state
notifications (store/ui.ts) → Nav bell badge
```

---

## 附录 C: 页面入口映射 (Page Entry Points)

| Route | Component | File | Init Actions |
|-------|-----------|------|-------------|
| `/` (Home) | `Home` | `src/pages/home.tsx` | `loadAssets()`, conditionally `loadIdentity()`, `loadBalance()`, `GET /earnings` |
| `/mydata` | `MyData` | `src/pages/mydata.tsx` | `loadAssets()`, `GET /capabilities`, `GET /earnings` |
| `/explore` | `Explore` | `src/pages/explore.tsx` | Delegates to sub-tab components |
| `/explore` (Browse) | `ExploreBrowse` | `src/pages/explore-browse.tsx` | `GET /assets` + `GET /capabilities` parallel |
| `/explore` (Portfolio) | `ExplorePortfolio` | `src/pages/explore-portfolio.tsx` | `GET /shares` |
| `/explore` (Stake) | `ExploreStake` | `src/pages/explore-stake.tsx` | `GET /staking` |
| `/explore` (Bounty) | `ExploreBounty` | `src/pages/explore-bounty.tsx` | Task market data |
| `/automation` | `Automation` | `src/pages/automation.tsx` | `loadInbox()`, `loadTrust()`, `GET /agent/status`, `GET /agent/config`, `GET /agent/history` |
| `/network` | `Network` | `src/pages/network.tsx` | `GET /identity`, `GET /node/role`, chain queries |

---

## 附录 D: 错误处理统一规范 (Error Handling Reference)

All API errors flow through `src/api/client.ts`:

| HTTP Status | i18n Key | User Message (en) | User Message (zh) |
|-------------|----------|-------------------|-------------------|
| 401 / 403 | `error-unauthorized` | Unauthorized | 未授权 |
| 404 | `error-not-found` | Not found | 未找到 |
| 429 | `error-rate-limit` | Rate limited | 请求过于频繁 |
| 500 / 502 / 503 | `error-server` | Server error | 服务器错误 |
| Timeout (AbortError) | `error-timeout` | Request timed out | 请求超时 |
| Network (TypeError) | `error-network` | Network error | 网络错误 |
| Other | `error-generic` | An error occurred | 发生错误 |

Timeouts:
- Standard requests: 30,000ms
- File uploads: 120,000ms
- Bundle uploads: 180,000ms
- Token fetch: 5,000ms
