# One call against the hosted server. Runs only with MAPLESTATS_LIVE=1.

test_that("search and get_data work against the hosted server", {
  skip_if_not(
    identical(Sys.getenv("MAPLESTATS_LIVE"), "1"),
    "set MAPLESTATS_LIVE=1"
  )
  client <- ms_client()

  found <- ms_search_tools("bank of canada exchange rate", client = client)
  expect_true(any(startsWith(found$name, "boc_")))

  data <- ms_get_data(
    "boc_get_observations",
    series_names = I("FXUSDCAD"),
    recent = 2,
    client = client
  )
  expect_equal(nrow(data), 2)
  expect_true("values_fxusdcad" %in% names(data))
  expect_equal(attr(data, "provenance")$source, "boc")
})
