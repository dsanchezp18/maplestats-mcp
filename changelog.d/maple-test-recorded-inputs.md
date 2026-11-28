### Added

- New Maple Test runs record their answer key, effective prompt, settings and
  available environment identifiers in a manifest beside the answers. Resuming
  refuses inconsistent inputs, and grading uses the saved key even after the
  working key changes. Legacy runs remain gradeable with an explicit limitation;
  reports identify the current adjudication and citation-cache inputs by hash.
