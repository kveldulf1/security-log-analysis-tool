---
name: explore-app
description: "Systematically explore a web application to create page documentation and feature inventory for future testing"
user-invocable: true
allowed-tools: Bash(playwright-cli:*), Read, Grep, Glob, Write
model: sonnet
---

# Explore App - Systematic Application Exploration

**Project:** $PROJECT
**Mode:** $MODE (headed/headless, default: headed)

## Goal

Systematic exploration of a new web application to create page documentation and feature inventory for future testing.

## Instructions

### Step 0: Mode Selection and playwright-cli Initialization

1. **Ask about browser mode:**
   - If `$MODE` is not provided or empty - ask: "Which browser mode? (headed/headless, default: headed)"
   - If `$MODE` is provided - use it
   - Save choice as `MODE` variable (headed or headless)

2. **Initialize playwright-cli:**
   - **IMPORTANT:** Before starting exploration, always invoke `/playwright-cli` with a task to initialize browser session
   - Task: "Open browser in [MODE] mode and prepare session for app exploration"
   - Use `--headed` flag if MODE=headed, or no flag if MODE=headless

### Step 1: Preparation and User Roles

1. Check if directory `.claude/$PROJECT/` exists
2. Check if file `.claude/$PROJECT/playwright-config.md` exists
   - If NOT - ask user for:
     - Application URL (login page)
     - Default browser (chrome/firefox/webkit)
     - Viewport (default 1920x1080)
   - Create `playwright-config.md` with this data
3. **Check user roles:**
   - Ask: "Does the application have different user roles (e.g., admin, user, employee)?"
   - If YES - ask for credentials for each role:
     - Role name (e.g., "admin", "user", "employee")
     - Username for this role
     - Password for this role
   - If NO - ask for single credentials (username/password)
4. Read `.claude/$PROJECT/playwright-config.md`
5. Read `rules/playwright-cli/SKILL.md`

### Step 2: Login and Session Saving

**If there are different user roles:**

For each role, execute separately:

1. Open browser (or use already open from Step 0): `playwright-cli open [URL] --browser=chrome --[MODE]`
2. Login with credentials for this role
3. Save session: `playwright-cli state-save auth-[role].json` (e.g., `auth-admin.json`, `auth-user.json`)
4. Take snapshot of page after login
5. Execute exploration (Steps 3-7) and save documentation in `.claude/$PROJECT/pages/[role]/`
6. Logout before moving to next role

**If there's only one role/no roles:**

1. Open browser (or use already open from Step 0): `playwright-cli open [URL] --browser=chrome --[MODE]`
2. If there are credentials - login
3. Save session: `playwright-cli state-save auth.json`
4. Take snapshot of page after login

### Step 3: Navigation Mapping

1. Snapshot of main page/dashboard
2. From snapshot, list all navigation elements:
   - Sidebar menu items (links, buttons)
   - Topbar buttons/dropdowns (language, notifications, profile)
   - Main navigation links
3. Save navigation structure

### Step 4: Page Exploration

For each menu item:

1. Click link/button
2. Wait for load (snapshot after navigation)
3. Collect information:
   - URL
   - Page title (h1 heading)
   - Subtitle/description
   - Main UI elements:
     - Tables (columns, row actions)
     - Forms (fields, buttons)
     - Statistics cards
     - Filters/search
     - Action buttons ("Add", "Export", etc.)
     - Context menus (3-dots)
     - Pagination
4. Go back or continue

### Step 5: Forms and Details Exploration

1. Find buttons like "Add", "New", "Create"
2. Open creation forms - document fields:
   - Field name
   - Type (textbox, combobox, checkbox)
   - Placeholder
   - Required or not
3. Enter details of an example record
4. Document details view and available actions

### Step 6: Global Elements (topbar)

1. Check notifications dropdown (bell icon)
2. Check user profile dropdown
3. Check language switcher (if exists)
4. Check sidebar toggle (if exists)

### Step 7: Feature Discovery

For each page/module, identify and document features:

1. **User Actions** - What can the user do?
   - Create/Add operations
   - Edit/Update operations
   - Delete/Remove operations
   - View/Read operations
   - Export/Download operations
   - Approval/Rejection workflows

2. **Data Management** - What data can user manage?
   - List views with filtering/sorting
   - Detail views
   - Forms for data entry
   - File uploads

3. **Business Workflows** - What processes are supported?
   - Multi-step processes
   - Status transitions
   - Approval chains
   - Notifications

4. **Document features using project terminology** - use exact labels from UI

### Step 8: Documentation Generation

**Directory structure for different roles:**

If there are different user roles:

- Create directories for each role: `.claude/$PROJECT/pages/[role]/` (e.g., `pages/admin/`, `pages/user/`, `pages/employee/`)
- For each role execute exploration separately (Steps 2-7) and save documentation in appropriate directory
- If no different roles - use standard `.claude/$PROJECT/pages/`

Generate files in appropriate directory (depending on role or main `pages/`):

#### `_index.md` - Application Overview

```markdown
# [Application Name] - Overview

## Metadata

- Base URL: [url]
- Exploration date: [date]
- Logged in as: [user]
- Available languages: [list]

## Navigation Tree

[URL list in tree form]

## Common Layout

### Sidebar

[Sidebar description]

### Topbar

[Top bar description - language, notifications, profile]

## Login Page

[URL, form elements]
```

#### For each page - separate file (e.g., `dashboard.md`, `clients.md`)

```markdown
# [Page Name]

## URL

`/admin/[path]`

## Type

[list/form/details/dashboard]

## UI Elements

### Header

- Heading: "[title]"
- Subtitle: "[description]"
- Buttons: [list]

### Statistics Cards (if any)

| Card  | Value | Caption |
| ----- | ----- | ------- |
| ...   | ...   | ...     |

### Filters (if any)

- [filter name] (type)

### Table (if any)

Columns: [column list]

### Context Menu (if any)

- [option 1]
- [option 2]

### Pagination

[description]

## Features

- **[Feature Name]**: [What user can do - use exact UI terminology]
- **[Feature Name]**: [What user can do - use exact UI terminology]
```

### Step 9: Terminology and Features Compilation

After generating all `pages/` files, compile them into `.claude/$PROJECT/TERMINOLOGY_AND_FEATURES.md`.

This file serves for ticket refinement and feature documentation.

1. **Read all files** `pages/**/*.md` (including `_index.md` and per-role files)

2. **Extract and compile:**

   **Features per module:**
   - Group features by page/module
   - Use exact terminology from UI
   - Include which roles have access

   **Terminology dictionary:**
   - User roles (with URL prefixes)
   - Navigation: all URLs → page names
   - Statuses (per entity)
   - Types (enumerations from UI)
   - Buttons and actions per page/module
   - Form fields per module
   - Table columns
   - Filters and search options
   - Dropdown options

3. **Create `.claude/$PROJECT/TERMINOLOGY_AND_FEATURES.md`** with structure:

```markdown
# [Project Name] - Terminology and Features

## Project Context

- Application: [name]
- Base URL: [url]
- Exploration date: [date]

## User Roles

| Role | URL Prefix | Access |
| ---- | ---------- | ------ |
| ...  | ...        | ...    |

## Feature List

### [Module Name] ([role])

| Feature | Description | UI Element |
| ------- | ----------- | ---------- |
| ...     | ...         | ...        |

## Terminology Dictionary

### Navigation

| URL | Page Name |
| --- | --------- |
| ... | ...       |

### Statuses

**[Entity]:** [status1], [status2], ...

### Types

**[Type category]:** [type1], [type2], ...

### Buttons and Actions

| Module | Buttons / Actions |
| ------ | ----------------- |
| ...    | ...               |

### Form Fields

| Form | Fields |
| ---- | ------ |
| ...  | ...    |

### Table Columns

| Table | Columns |
| ----- | ------- |
| ...   | ...     |

### Filters

| Page | Available Filters |
| ---- | ----------------- |
| ...  | ...               |

## Ticket Templates

### Bug

[template]

### Task

[template]

---

## Ticket to Rewrite

> Paste raw ticket content here.
```

### Step 10: Completion

1. **Do NOT close browser automatically**
2. Show list of created files:
   - If different roles: show directory structure `pages/[role]/` for each role
   - If single role: show files in `pages/`
   - Always mention `TERMINOLOGY_AND_FEATURES.md` as created/updated
3. Summarize:
   - Number of mapped pages (per role if different roles)
   - Number of features discovered
   - Access differences between roles (if different roles)
4. Ask: "Do you want to continue exploration or close session?"

## Snapshot Strategy

**IMPORTANT:** Snapshots `.yml` are a working tool, NOT documentation.

- Generate new snapshots during exploration
- Do NOT keep them for later use
- References (e1, e2...) change with each render
- Documentation in `pages/*.md` is the source of truth

## Usage Example

```
/explore-app project:myapp mode:headed
/explore-app project:newapp mode:headless
```

**Example with different roles:**

1. Invoke `/explore-app project:myapp` (without specifying mode)
2. System asks: "Which browser mode? (headed/headless, default: headed)"
3. User responds: "headed"
4. System automatically invokes `/playwright-cli` with task: "Open browser in headed mode and prepare session for app exploration"
5. System asks about user roles
6. User provides: admin (user: admin@test.com, pass: admin123), user (user: user@test.com, pass: user123)
7. System creates directories: `pages/admin/` and `pages/user/`
8. System executes exploration for each role separately and saves documentation in appropriate directories
9. System compiles `TERMINOLOGY_AND_FEATURES.md` with all discovered features and terminology
