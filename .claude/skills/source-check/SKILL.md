---
name: source-check
description: Checks a draft, research note or page for unsourced claims, media-only claims about named providers, individual names, unqualified counts and banned dashes before it is published or committed. Use on any file that will be shown to the public or shared.
argument-hint: "[file path]"
context: fork
agent: general-purpose
allowed-tools: Read Grep Glob WebFetch
---

# Source check

Review the file at $ARGUMENTS. Do not edit it. Report problems only.

Check every factual claim and flag:

1. **No source**: no URL or record ID next to the claim.
2. **Media only about a named provider or service**: allowed in internal research, never in public
   output.
3. **Individual named**: any child, family member, educator or non-executive staff member.
4. **Count without a denominator or window**: for example '12 breaches' with no period or base.
5. **Conflated terms**: breach, confirmed breach, enforcement action, prosecution and conviction
   used as if interchangeable.
6. **Implied safety from absence**: wording that suggests no flag means safe.
7. **Unmarked uncertainty**: a figure that is not from a primary source and lacks `[Verify This]`.
8. **Style**: em dashes or en dashes.

For a sample of up to five claims, open the cited URL and confirm the source says what the file
says.

Return a table: line number, issue type, the text, and the fix. End with PASS or FAIL. FAIL if any
issue of type 2, 3 or a failed spot-check is present.
