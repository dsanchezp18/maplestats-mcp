# The client against recorded responses from the hosted server (no network).

boc_call <- function(client, series = "FXUSDCAD") {
  ms_call_tool(
    "boc_get_observations",
    series_names = I(series),
    recent = 3,
    client = client
  )
}

test_that("one session is opened and tools go through call_tool", {
  server <- local_fake_server()
  client <- test_client()

  boc_call(client)
  boc_call(client)

  methods <- purrr::map_chr(server$bodies(), "method")
  expect_equal(
    methods,
    c("initialize", "notifications/initialized", "tools/call", "tools/call")
  )
  call <- server$bodies()[[3]]$params
  expect_equal(call$name, "call_tool")
  expect_equal(call$arguments$name, "boc_get_observations")
  expect_equal(
    server$seen[[3]]$headers$`mcp-protocol-version`,
    "2025-06-18"
  )
})

test_that("search_tools returns a tibble of tools", {
  server <- local_fake_server()
  found <- ms_search_tools(
    "bank of canada exchange rate",
    client = test_client()
  )

  expect_s3_class(found, "tbl_df")
  expect_named(found, c("name", "description", "input_schema"))
  expect_gt(nrow(found), 0)
  expect_true(any(startsWith(found$name, "boc_")))
  expect_type(jsonlite::fromJSON(found$input_schema[[1]]), "list")
  expect_equal(server$bodies()[[3]]$params$name, "search_tools")
})

test_that("a search with no match is an empty tibble", {
  local_fake_server()
  found <- ms_search_tools("zzqx", client = test_client())

  expect_equal(nrow(found), 0)
  expect_named(found, c("name", "description", "input_schema"))
})

test_that("plan_query is called directly", {
  server <- local_fake_server()
  plan <- ms_plan_query("Unemployment rate in Alberta", client = test_client())

  expect_gt(length(plan$topics[[1]]$steps), 0)
  expect_equal(server$bodies()[[3]]$params$name, "plan_query")
})

test_that("get_data tidies Bank of Canada observations", {
  local_fake_server()
  data <- ms_get_data(
    "boc_get_observations",
    series_names = I("FXUSDCAD"),
    recent = 3,
    client = test_client()
  )

  expect_named(data, c("ref_date", "values_fxusdcad", "non_numeric"))
  expect_equal(nrow(data), 3)
  expect_type(data$values_fxusdcad, "double")
  expect_true(all(is.na(data$non_numeric)))
  expect_equal(attr(data, "provenance")$source, "boc")
  expect_match(
    attr(data, "citation"),
    "^Source: boc\\. https://www\\.bankofcanada\\.ca/"
  )
  expect_equal(attr(data, "left_out")$series, "[object]")
  expect_equal(attr(data, "tool"), "boc_get_observations")
})

test_that("get_data unnests a series' observations", {
  local_fake_server()
  data <- ms_get_data(
    "wds_get_data_from_vectors",
    vector_ids = I(2062815),
    latest_n = 3,
    client = test_client()
  )

  expect_equal(nrow(data), 3)
  expect_true(all(
    c("vector_id", "ref_period", "value", "context_citation") %in% names(data)
  ))
  expect_equal(unique(data$vector_id), 2062815)
  expect_equal(attr(data, "citation"), data$context_citation[[1]])
  expect_match(attr(data, "citation"), "Table 14-10-0287-01", fixed = TRUE)
})

test_that("a tool error raises with the server's message", {
  local_fake_server()
  expect_error(
    boc_call(test_client(), "NOPE_XX"),
    "Series NOPE_XX not found",
    class = "maplestats_error"
  )
})

test_that("reproduce_code returns the scripts", {
  local_fake_server()
  code <- ms_reproduce_code(
    "boc_get_observations",
    list(series_names = I("FXUSDCAD"), recent = 3),
    language = "python",
    client = test_client()
  )

  expect_equal(code$scripts[[1]]$language, "python")
  expect_match(code$scripts[[1]]$code, "polars", fixed = TRUE)
})

test_that("an expired session is reopened once", {
  server <- local_fake_server()
  client <- test_client()
  boc_call(client)

  expired <- new.env()
  expired$done <- FALSE
  server$override <- function(request) {
    if (sent_body(request)$method == "tools/call" && !expired$done) {
      expired$done <- TRUE
      return(httr2::response(status_code = 404))
    }
    NULL
  }
  boc_call(client)

  methods <- purrr::map_chr(server$bodies(), "method")
  expect_equal(sum(methods == "initialize"), 2)
  expect_equal(methods[[length(methods)]], "tools/call")
})

test_that("a rate limit raises with retry_after", {
  server <- local_fake_server()
  server$override <- function(request) {
    httr2::response(status_code = 429, headers = list(`retry-after` = "12"))
  }

  error <- expect_error(
    ms_search_tools("anything", client = test_client()),
    class = "maplestats_rate_limited"
  )
  expect_equal(error$retry_after, 12)
})

test_that("an HTTP error raises", {
  server <- local_fake_server()
  server$override <- function(request) httr2::response(status_code = 503)

  expect_error(
    ms_search_tools("anything", client = test_client()),
    "HTTP 503",
    class = "maplestats_error"
  )
})

test_that("url and token come from the environment", {
  withr::local_envvar(
    MAPLESTATS_URL = "https://self.hosted/mcp",
    MAPLESTATS_TOKEN = "secret"
  )
  server <- local_fake_server()
  ms_search_tools("bank of canada exchange rate", client = ms_client())

  expect_equal(server$seen[[1]]$url, "https://self.hosted/mcp")
  expect_equal(
    httr2::req_get_headers(server$seen[[1]], "reveal")$Authorization,
    "Bearer secret"
  )
})

test_that("names are cleaned as janitor does", {
  expect_equal(
    clean_names(
      c("context.citation", "values.FXUSDCAD", "refPer", "a.b", "a_b")
    ),
    c("context_citation", "values_fxusdcad", "ref_per", "a_b", "a_b_2")
  )
})
