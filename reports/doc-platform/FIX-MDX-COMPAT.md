## Task

Fix MDX compatibility in `generate-documentation.js`

## Context

This script generates API reference documentation as `.mdx` files using `jsii-docgen`. The generated files are copied into a Mintlify docs site. Mintlify parses all files (both `.md` and `.mdx`) with the MDX parser, which treats `{` as JSX expression delimiters and `<!-- -->` as invalid syntax. The current output has ~2,400 MDX parsing errors across 25 generated files.

## There are 4 categories of problematic content that need escaping/replacing

All occur in prose text (outside fenced code blocks). Content inside fenced code blocks is NOT parsed by MDX and must be left untouched.

### 1. HTML comments → MDX comments

- **Line 142** in the generator: `<!-- This file is generated through yarn generate-docs -->`
- **Fix**: Change to `{/* This file is generated through yarn generate-docs */}`
- **Count**: 25 occurrences (1 per file)

### 2. `{@link url text}` → markdown links

- jsii-docgen produces JSDoc-style links: `{@link https://developer.hashicorp.com/terraform/language/functions/abs abs}`
- MDX chokes on the `{` trying to parse it as a JSX expression
- **Fix**: Convert to standard markdown links: `[abs](https://developer.hashicorp.com/terraform/language/functions/abs)`
- **Pattern**: `{@link <URL> <linkText>}` → `[<linkText>](<URL>)`
- **Count**: ~2,360 occurrences across 15 files (the bulk of all errors)

### 3. `${...}` template literal syntax in prose descriptions

- Example: `True when ${} should not be parsed, and treated as literals.`
- MDX tries to parse `${}` as a JSX expression
- **Fix**: Escape as `\$\{\}` or `$\{\}`
- **Count**: ~44 occurrences across 12 files

### 4. Bare `{` in prose/table cells (JSON-like or TypeScript type syntax)

- Example in table cell: `Adds an { "error": < message > } metadata entry to this construct.`
- Example in type column: `<code>{[ key: string ]: StackManifest}</code>`
- **Fix**: Escape opening braces as `\{` when they appear in prose/table text outside of code fences
- **Count**: ~200 occurrences across a few files

## Implementation approach

Add a new sanitization function (similar to the existing `replaceAngleBracketsInDocumentation`) that processes the rendered markdown string. It should:

1. **Be code-fence-aware**: Split content by fenced code block boundaries (`` ``` ``). Only transform text outside code fences. Rejoin after processing.

2. **Apply transformations in this order on non-code-fence content**:
   - Replace `{@link <URL> <text>}` with `[<text>](<URL>)` using a regex like `/\{@link\s+(https?:\/\/\S+)\s+([^}]+)\}/g`
   - Escape remaining `{` characters as `\{` (this covers categories 3 and 4)

3. **Fix the HTML comment** on line 142: change `<!-- ... -->` to `{/* ... */}` in the `compose` template literal.

## Where to apply the new sanitizer

Apply it in the `compose` function (line 137-150), wrapping the output of `replaceAngleBracketsInDocumentation` or chaining after it. The compose function is the single place where final output is assembled before writing to disk.

## Testing

After making changes, regenerate the docs and validate:

```bash
cd /Users/vincentdesmet/cdktn/cdk-terrain
yarn generate-docs:api
```

Then copy to the docs site and validate:

```bash
cp -r website/docs/cdktn/api-reference/* /Users/vincentdesmet/cdktn/docs/content/api-reference/
cd /Users/vincentdesmet/cdktn/docs/content && npx mintlify validate
```

## Success criteria

- `mintlify validate` shows zero parsing errors for api-reference files
- The rendered markdown links should be functional (verify a few `{@link}` conversions look correct)
- Content inside fenced code blocks is unchanged
