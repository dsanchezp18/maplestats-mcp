### Changed

- `statcan_delta_list_tables`: the `detail` parameter is now `include_members`
  (same meaning: dimension members and correction notes for one `product_id`).
  `detail` is call_tool's argument for a brief or full result, and the server
  removes it from every data tool's arguments, so the old parameter could never
  be set and asking for members returned none. Pass `include_members=True`
  instead. A test now fails if any tool takes a parameter named `detail`.
