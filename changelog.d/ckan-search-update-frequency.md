### Changed

- `ckan_search_datasets`: each result now states the dataset's update frequency
  (`update_frequency`) where its portal publishes one: federal (in plain words),
  Ontario, Alberta, Québec, Northwest Territories, Yukon, Montréal, Toronto and
  Niagara. Before, it was only in `ckan_get_dataset`'s `extras`, and since the
  compact `search_tools` lines no tool's one-line description said where to find
  it: in the Maple Test, two answers in three to an Ontario question stopped at the
  search result and said the frequency was not given. The one-line descriptions of
  `ckan_search_datasets` and `ckan_get_dataset` now name the fields each returns.
