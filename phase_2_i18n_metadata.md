Role: Software Internationalization (i18n) & File Systems Security Specialist.
Task: Evaluate non-Latin (Unicode) audio track support and file export integrity. Do not write or edit production code.

Investigate:
1. Unicode Metadata Extraction:
   - How are non-Latin character sets (Chinese, Japanese Kanji/Kana, Cyrillic, Georgian, etc.) parsed from audio tags (ID3/Vorbis)?
   - Are `Title` / `Artist` separated correctly into Romanised and Unicode fields in `.osu` headers (`TitleUnicode`, `ArtistUnicode`)?
2. File System & Path Sanitization:
   - Check file naming and path creation logic when exporting `.osu` and `.osz` packages.
   - Are non-ASCII filenames properly sanitized, or do they risk OS encoding errors (Windows CP1252 vs. UTF-8)?
3. Fallback Romanisation:
   - Is there a transliteration fallback if Romanised metadata is missing?

Output Requirement:
Save the complete diagnostic report with code references directly to `audit_reports/phase_2_i18n_metadata.md`.
Also print a brief terminal summary and end with: "Phase 2 Complete. Saved to audit_reports/phase_2_i18n_metadata.md. Ready for Phase 3."