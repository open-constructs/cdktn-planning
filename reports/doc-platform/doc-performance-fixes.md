# Doc Platform Performance Fixes — Handover

## Problem Statement

The generated API reference documentation has two issues on the Mintlify doc platform:

### 1. Document Size

The 25 generated `.mdx` files are too large for Mintlify to handle performantly. The largest files:

| File | Lines | Size |
|------|------:|-----:|
| `python/constructs.mdx` | 17,938 | 620K |
| `java/constructs.mdx` | 17,175 | 648K |
| `python/classes.mdx` | 14,452 | 444K |
| `typescript/classes.mdx` | 13,127 | 440K |
| `go/classes.mdx` | 13,127 | 448K |
| `typescript/structs.mdx` | 9,498 | 340K |
| `**/structs.mdx` | ~10,162 | ~350K |

Each of these files contains documentation for **dozens of classes/constructs** in a single page. For example, `typescript/constructs.mdx` has 40 constructs, each with full docs for initializers, methods, properties, and parameters.

### 2. Table of Contents (TOC) Heading Depth

Mintlify's sidebar TOC only renders well with H2/H3 headings. The current documents start at **H3** and go down to **H6**:

```
### App                          ← H3: Construct name
#### Initializers                ← H4: Section (Initializers, Methods, Properties, Static Functions)
##### `config`                   ← H5: Individual member (method name, property name)
###### `fromStack`               ← H6: Method parameter
```

Since the topic heading (e.g., `## Constructs`) is stripped (it becomes the page title via frontmatter), the deepest structural heading visible is H3. Mintlify's TOC doesn't usefully navigate H4-H6 content, resulting in a flat or missing sidebar outline.

## Proposed Solution

Split each topic file further — **one file per class/construct** — and shift heading depths so the class name becomes H2 and section headings start at H3:

### Before (current)

```
typescript/constructs.mdx     (12,379 lines, 40 constructs, headings H3-H6)
typescript/classes.mdx        (13,127 lines, 52 classes, headings H3-H6)
```

### After (proposed)

```
typescript/constructs/app.mdx                  (~250 lines, headings H2-H5)
typescript/constructs/azurerm-backend.mdx       (~200 lines, headings H2-H5)
typescript/constructs/cloud-backend.mdx         ...
typescript/classes/aspects.mdx                  ...
```

Each per-class file would have:

```
## App                             ← H2 (was H3): class name — appears in TOC
### Initializers                   ← H3 (was H4): visible in TOC
#### `config`                      ← H4 (was H5): visible in TOC
##### `fromStack`                  ← H5 (was H6): parameter detail
```

### File Count Impact

Current: **25 files** (5 languages × 5 topics)

Proposed: **~920 files** (5 languages × ~184 classes/constructs/structs/protocols/enums). Breakdown for TypeScript:

| Topic | H3 Count | Files |
|-------|----------|-------|
| Constructs | 40 | 40 |
| Classes | 52 | 52 |
| Structs | 66 | 66 |
| Protocols | 24 | 24 |
| Enums | 2 | 2 |
| **Total (TS)** | **184** | **184** |

## Implementation Plan

### Step 1: Extend `splitByHeading` to Support Two-Level Splitting

The current `splitByHeading(tree, 2)` splits by H2 into topic sections. Extend it to do a second split within each topic by H3 (individual class/construct names):

```js
// Current: one level
const sections = splitByHeading(tree, 2);
// sections = Map { "Constructs" => subtree, "Classes" => subtree, ... }

// Proposed: two levels
const topicSections = splitByHeading(tree, 2);
for (const [topic, topicTree] of topicSections) {
  const classSections = splitByHeading(topicTree, 3);
  // classSections = Map { "App" => subtree, "AzurermBackend" => subtree, ... }
}
```

The existing `splitByHeading` function already works for any depth — just call it twice.

### Step 2: Add `adjustHeadingDepth(tree, offset)`

Shift all heading depths in a subtree by a negative offset, so H3→H2, H4→H3, etc.:

```js
function adjustHeadingDepth(tree, offset) {
  visit(tree, 'heading', (node) => {
    node.depth = Math.max(1, node.depth - offset);
  });
}
```

Call `adjustHeadingDepth(classSubtree, 1)` after splitting by H3 to promote all headings by one level.

### Step 3: Generate File Paths from Class Names

Convert heading text to kebab-case filenames:

```js
function toKebabCase(name) {
  // "DataTerraformRemoteStateAzurerm" → "data-terraform-remote-state-azurerm"
  return name
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .replace(/([A-Z])([A-Z][a-z])/g, '$1-$2')
    .toLowerCase();
}

// Output path: typescript/constructs/data-terraform-remote-state-azurerm.mdx
```

### Step 4: Dynamically Generate `docs.json` Navigation

The `docs.json` file at `/Users/vincentdesmet/cdktn/docs/content/docs.json` currently hardcodes 25 page references in the API Reference tab:

```json
{
  "group": "TypeScript",
  "pages": [
    "api-reference/typescript/constructs",
    "api-reference/typescript/classes",
    ...
  ]
}
```

This must be dynamically generated to include all ~920 per-class pages. Two options:

**Option A: Generator writes `docs.json`**

The doc generator reads the existing `docs.json`, replaces the API Reference tab's groups with the actual generated file list, and writes it back. The generator already knows all the class names and file paths.

**Option B: Generator writes a `navigation-fragment.json`**

The generator writes a JSON fragment containing just the API Reference navigation, and a separate script merges it into `docs.json`. This keeps the generator focused on docs and separates navigation concerns.

**Recommended**: Option A — the generator already has all the information and it's simpler. The navigation structure would become:

```json
{
  "group": "TypeScript",
  "pages": [
    {
      "group": "Constructs",
      "pages": [
        "api-reference/typescript/constructs/app",
        "api-reference/typescript/constructs/azurerm-backend",
        "api-reference/typescript/constructs/cloud-backend",
        ...
      ]
    },
    {
      "group": "Classes",
      "pages": [
        "api-reference/typescript/classes/aspects",
        ...
      ]
    },
    ...
  ]
}
```

### Step 5: Update `compose()` Frontmatter

Each per-class file needs updated frontmatter:

```yaml
---
title: "TypeScript: App"
sidebarTitle: App
description: CDKTN Core API Reference for App in TypeScript.
---
```

## Current AST Implementation

The pipeline in `generate-documentation.js` (as of commit `f2cc55fec`):

```
jsii-docgen → markdown string
       │
       ▼
  remark-parse → full MDAST tree
       │
       ▼
  splitByHeading(tree, 2) → Map<topic, MDAST subtree>
       │
       ▼
  sanitizeAst(subtree) → walks text/html/link nodes, skips code/inlineCode
       │
       ▼
  remark-stringify → clean markdown string
       │
       ▼
  postProcessForMdx() → autolinks, |‑in‑<code>, lone <, { escaping
       │
       ▼
  compose() → frontmatter + content → .mdx files
```

### Key Functions

| Function | Purpose |
|----------|---------|
| `splitByHeading(tree, depth)` | Splits MDAST tree at headings of given depth. Returns `Map<headingText, {type:"root", children}>`. Trims heading text (handles trailing space from anchor tags). |
| `sanitizeAst()` | Remark plugin via `visit()`. Skips `code`/`inlineCode` nodes entirely. Handles: `{@link}` → link nodes, `<Foo>` → `< Foo >` in text/html nodes, terraform doc links → absolute URLs on link nodes. |
| `stringifyTree(subtree)` | Wraps `unified().use(remarkStringify, opts).stringify(subtree)`. Options: `bullet: "-"`, `emphasis: "*"`, `strong: "*"`. |
| `postProcessForMdx(markdown)` | String-level post-processing with code-fence extraction/restoration. Handles: autolinks `<url>` → `[url](url)`, `\|` inside `<code>`, lone `<` → `&lt;`, `{` → `\{`. |
| `compose(lang, topic, content)` | Wraps content with Mintlify MDX frontmatter. |

### Why Some Fixes Are AST-Level and Others Are Post-Processing

| Fix | Level | Reason |
|-----|-------|--------|
| `{@link}` → links | AST | Requires node splicing (text → text + link + text) |
| `<Foo>` spacing | AST | Must skip `code`/`inlineCode` nodes |
| Terraform doc links | AST | Direct URL mutation on link nodes |
| `{` → `\{` | Post | `remark-stringify` double-escapes `\` before punctuation |
| `<url>` autolinks | Post | `remark-stringify` generates autolink format; no option to disable |
| `\|` in `<code>` | Post | `remark-parse` splits inline HTML across multiple MDAST nodes |
| Lone `<` → `&lt;` | Post | Same multi-node issue; also catches `<=`, `<` in prose |

### Dependencies (No New Ones Needed)

All in `tools/documentation-generation/package.json`:

- `remark-parse@^11` — markdown → MDAST parser
- `remark-stringify@^11` — MDAST → markdown serializer
- `unified@^11` — plugin pipeline coordinator
- `unist-util-visit@^5` — AST tree walker
- `jsii-docgen@^10` — generates markdown from JSII assembly

**Note**: `remark-gfm` is NOT installed. This means `remark-parse` does NOT parse GFM tables into `table`/`tableRow`/`tableCell` nodes — table lines pass through as paragraphs with inline HTML. This is why `|`-in-`<code>` must be fixed in post-processing. Adding `remark-gfm` would allow AST-level table handling but is a new dependency.

## Testing & Validation Process

### Step 1: Generate Docs

```bash
# From repo root (builds packages first):
yarn generate-docs:api

# Or from the tool directory (packages must already be built):
cd tools/documentation-generation
node ./generate-documentation.js ../../
```

Output: `website/docs/cdktn/api-reference/<language>/<topic>.mdx`

### Step 2: Copy to Docs Site

```bash
cp -r website/docs/cdktn/api-reference/* /Users/vincentdesmet/cdktn/docs/content/api-reference/
```

### Step 3: Validate with Mintlify

```bash
cd /Users/vincentdesmet/cdktn/docs/content && npx mintlify validate
```

**Critical**: `mintlify validate` must run from the directory containing `docs.json` (i.e., `docs/content/`). Running from the workspace root or using `pnpm exec` won't find the config.

### What to Check

1. **Zero parsing errors** — `mintlify validate` should report only navigation warnings, no `parsing error` lines
2. **TypeScript code blocks** — `import { Foo }` must NOT have `\{` (the original bug)
3. **Python code blocks** — `-> str` must NOT be broken to `- >` (the original bug)
4. **Prose braces** — `\{[ key: string ]: any}` in table cells must be escaped
5. **Autolinks** — no `<https://...>` in prose (must be `[url](url)`)
6. **Spot-check** all languages × topics (25 files currently)

### Quick Validation Commands

```bash
# Check for escaped braces in code blocks (should be 0):
grep -r 'import \\{' website/docs/cdktn/api-reference/typescript/

# Check Python arrow operator preserved (should have matches):
grep -c '\->' website/docs/cdktn/api-reference/python/constructs.mdx

# Check braces escaped in prose (should have matches):
grep -c '\\{' website/docs/cdktn/api-reference/typescript/constructs.mdx

# Check no autolinks remain:
grep -c '<https://' website/docs/cdktn/api-reference/**/*.mdx
```

## Workspace Layout

```
/Users/vincentdesmet/cdktn/
├── cdk-terrain/                          # Main monorepo
│   ├── packages/cdktn/                   # Core JSII library (source for docs)
│   ├── packages/cdktn/.jsii              # JSII assembly (input to jsii-docgen)
│   ├── tools/documentation-generation/
│   │   ├── generate-documentation.js     # The doc generator script (ESM)
│   │   ├── package.json                  # type: "module", local deps on cdktn + constructs
│   │   ├── node_modules/                 # Local install (jsii-docgen resolves assembly here)
│   │   ├── README.md                     # Pipeline documentation
│   │   └── FIX-MDX-COMPAT.md            # Original planning doc for MDX fixes (can be deleted)
│   └── website/docs/cdktn/api-reference/ # Generated output (25 .mdx files)
│       ├── typescript/
│       ├── python/
│       ├── java/
│       ├── go/
│       └── csharp/
│
└── docs/                                 # Mintlify docs site (separate repo)
    └── content/
        ├── docs.json                     # Mintlify config — navigation, theme, etc.
        └── api-reference/                # Copy target for generated docs
            ├── index.mdx                 # API reference landing page
            ├── typescript/
            ├── python/
            ├── java/
            ├── go/
            └── csharp/
```

### Key Details

- `tools/documentation-generation` is **excluded from workspace hoisting** — it needs its own `node_modules/` with `cdktn` and `constructs` for jsii-docgen to resolve the JSII assembly
- The generator is an **ESM module** (`"type": "module"` in package.json) — uses `import` and dynamic `await import()` for remark/unified
- `docs.json` lives in the **separate docs repo**, not in cdk-terrain — it must be updated when the file structure changes
- The `docs.json` navigation currently references paths without `.mdx` extension (Mintlify convention)
- The `docs.json` navigation warnings from `mintlify validate` (e.g., `"api-reference/typescript/constructs" is referenced but file does not exist`) are **expected** — they indicate the navigation references pages by slug, and Mintlify resolves them at build time

## Edge Cases to Watch

1. **Empty topics**: Some language × topic combinations may produce empty subtrees (e.g., if a topic has no members). The current code skips these: `if (!subtree || subtree.children.length === 0) return;`. The per-class split should do the same.

2. **Duplicate heading text**: `splitByHeading` uses heading text as Map keys. Within a topic, class names are unique. But section headings like "Methods", "Properties" repeat across classes — this is fine because the second-level split produces separate subtrees per class.

3. **Heading anchor IDs**: jsii-docgen generates headings with `<a name="..." id="...">` anchors (e.g., `### App <a name="App" id="cdktn.App"></a>`). These become html child nodes in MDAST. `splitByHeading` extracts the text child and ignores the anchors. After heading depth adjustment, the anchors remain unchanged — cross-references within a file will still work, but cross-file links (if any) would need updating.

4. **File naming collisions**: Some class names may produce the same kebab-case filename. Check for collisions after generating the file list. If needed, use the full `id` from the anchor tag instead of the heading text.

5. **`docs.json` size**: With ~920 pages, the navigation section of `docs.json` will be large. Consider using Mintlify's `"expanded": false` option on the language/topic groups to keep the sidebar manageable.
