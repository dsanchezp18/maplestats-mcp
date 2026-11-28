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
  expect_named(found, search_columns)
  expect_gt(nrow(found), 0)
  expect_true(any(startsWith(found$name, "boc_")))
  schema <- jsonlite::fromJSON(found$input_schema[[1]])
  expect_gt(length(schema$properties), 0)
  expect_true(all(is.na(found$arguments)))
  call <- server$bodies()[[3]]$params
  expect_equal(call$name, "search_tools")
  expect_equal(call$arguments$detail, "full")
})

test_that("a brief search keeps the argument signature", {
  local_fake_server()
  found <- ms_search_tools(
    "bank of canada exchange rate",
    client = test_client(),
    detail = "brief"
  )

  expect_named(found, search_columns)
  expect_gt(nrow(found), 0)
  expect_true(startsWith(found$arguments[[1]], "{"))
  expect_true(all(is.na(found$input_schema)))
})

for (refusal in old_server_errors) {
  test_that(paste("search falls back without detail:", refusal), {
    server <- local_fake_server()

    # A server before the compact search rejects `detail` and answers the
    # full form.
    server$override <- function(request) {
      body <- sent_body(request)
      if (!identical(body$method, "tools/call")) {
        return(NULL)
      }
      if (is.null(body$params$arguments$detail)) {
        return(sse_response(recorded_body("search_tools", body$id)))
      }
      error_response(body$id, refusal)
    }
    found <- ms_search_tools(
      "bank of canada exchange rate",
      client = test_client()
    )

    expect_gt(nrow(found), 0)
    expect_false(is.na(found$input_schema[[1]]))
    bodies <- server$bodies()
    expect_null(bodies[[length(bodies)]]$params$arguments$detail)
  })
}

for (refusal in old_server_errors) {
  test_that(paste("data calls fall back without detail:", refusal), {
    server <- local_fake_server()

    # A server before 0.6.0 does not know call_tool's `detail`; it answers in
    # full.
    server$override <- function(request) {
      body <- sent_body(request)
      is_call <- identical(body$method, "tools/call")
      if (is_call && !is.null(body$params$arguments$detail)) {
        return(error_response(body$id, refusal))
      }
      NULL
    }
    data <- ms_get_data(
      "boc_get_observations",
      series_names = I("FXUSDCAD"),
      recent = 3,
      client = test_client()
    )

    expect_equal(nrow(data), 3)
    calls <- server$bodies() |>
      purrr::keep(\(body) identical(body$method, "tools/call")) |>
      purrr::map("params")
    expect_length(calls, 2)
    expect_equal(calls[[1]]$arguments$detail, "full")
    expect_equal(calls[[2]]$name, "call_tool")
    expect_null(calls[[2]]$arguments$detail)
    expect_equal(calls[[2]]$arguments$arguments$recent, 3)

    # The raw call falls back the same way.
    raw <- boc_call(test_client())
    expect_equal(raw$provenance$source, "boc")
  })
}

for (message in not_the_refusal) {
  test_that(paste("a detail-only error is not repeated:", message), {
    server <- local_fake_server()

    # The tool's own error, not a refusal of the argument: one call each for
    # the raw call, the data call and the search, and each raises.
    server$override <- function(request) {
      body <- sent_body(request)
      if (identical(body$method, "tools/call")) {
        return(error_response(body$id, message))
      }
      NULL
    }

    expect_error(boc_call(test_client()), class = "maplestats_error")
    expect_error(
      ms_get_data(
        "boc_get_observations",
        series_names = I("FXUSDCAD"),
        recent = 3,
        client = test_client()
      ),
      class = "maplestats_error"
    )
    expect_error(
      ms_search_tools("bank of canada exchange rate", client = test_client()),
      class = "maplestats_error"
    )
    methods <- purrr::map_chr(server$bodies(), "method")
    expect_equal(sum(methods == "tools/call"), 3)
  })
}

test_that("the repeat without detail is made once", {
  server <- local_fake_server()

  # A server that refuses `detail` and then fails the repeat too: two calls,
  # then the error reaches the caller.
  server$override <- function(request) {
    body <- sent_body(request)
    if (identical(body$method, "tools/call")) {
      return(error_response(body$id, old_server_errors[[1]]))
    }
    NULL
  }

  expect_error(
    ms_get_data(
      "boc_get_observations",
      series_names = I("FXUSDCAD"),
      recent = 3,
      client = test_client()
    ),
    "detail is not a parameter",
    class = "maplestats_error"
  )
  calls <- server$bodies() |>
    purrr::keep(\(body) identical(body$method, "tools/call")) |>
    purrr::map("params")
  expect_length(calls, 2)
  expect_equal(calls[[1]]$arguments$detail, "full")
  expect_null(calls[[2]]$arguments$detail)
})

test_that("the raw call passes detail to the server's own tools", {
  server <- local_fake_server()
  client <- test_client()

  # search_tools takes `detail` itself, so it goes in its arguments, as given.
  ms_call_tool(
    "search_tools",
    query = "bank of canada exchange rate",
    detail = "full",
    client = client
  )
  call <- server$bodies()[[3]]$params
  expect_equal(call$name, "search_tools")
  expect_equal(
    call$arguments,
    list(query = "bank of canada exchange rate", detail = "full")
  )

  # Without one, nothing is added.
  ms_call_tool(
    "plan_query",
    question = "Unemployment rate in Alberta",
    client = client
  )
  expect_equal(
    server$bodies()[[4]]$params$arguments,
    list(question = "Unemployment rate in Alberta")
  )
})

test_that("plan_query has no detail and the server says so", {
  server <- local_fake_server()
  server$override <- function(request) {
    body <- sent_body(request)
    if (identical(body$method, "tools/call")) {
      return(error_response(
        body$id,
        "detail is not a parameter of this tool; parameters: question, lang"
      ))
    }
    NULL
  }

  expect_error(
    ms_call_tool(
      "plan_query",
      question = "Unemployment rate in Alberta",
      detail = "full",
      client = test_client()
    ),
    "detail is not a parameter",
    class = "maplestats_error"
  )
  calls <- server$bodies() |>
    purrr::keep(\(body) identical(body$method, "tools/call"))
  expect_length(calls, 1)
  expect_equal(
    calls[[1]]$params,
    list(
      name = "plan_query",
      arguments = list(
        question = "Unemployment rate in Alberta",
        detail = "full"
      )
    )
  )
})

test_that("a search with no match is an empty tibble", {
  local_fake_server()
  found <- ms_search_tools("zzqx", client = test_client())

  expect_equal(nrow(found), 0)
  expect_named(found, search_columns)
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

  # A full result carries every field: non_numeric is null on every row here.
  expect_named(data, c("ref_date", "values_fxusdcad", "non_numeric"))
  expect_equal(nrow(data), 3)
  expect_type(data$values_fxusdcad, "double")
  expect_equal(attr(data, "provenance")$source, "boc")
  expect_match(
    attr(data, "citation"),
    "^Source: boc\\. https://www\\.bankofcanada\\.ca/"
  )
  expect_equal(
    attr(data, "left_out"),
    list(series = "[object]", transformed = NA)
  )
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

test_that("data tools are called with full detail", {
  server <- local_fake_server()
  client <- test_client()

  boc_call(client)
  ms_get_data(
    "boc_get_observations",
    series_names = I("FXUSDCAD"),
    recent = 3,
    client = client
  )

  calls <- server$bodies() |>
    purrr::keep(\(body) identical(body$method, "tools/call")) |>
    purrr::map("params")
  expect_length(calls, 2)
  for (call in calls) {
    # `detail` is call_tool's own argument, beside `name` and `arguments`.
    expect_equal(call$name, "call_tool")
    expect_equal(call$arguments$detail, "full")
    expect_equal(call$arguments$arguments$recent, 3)
    expect_null(call$arguments$arguments$detail)
  }
})

test_that("call_tool can ask for the brief answer", {
  server <- local_fake_server()
  ms_call_tool(
    "boc_get_observations",
    series_names = I("FXUSDCAD"),
    recent = 3,
    detail = "brief",
    client = test_client()
  )

  call <- server$bodies()[[3]]$params$arguments
  expect_equal(call$detail, "brief")
  expect_equal(call$arguments$recent, 3)
  expect_null(call$arguments$detail)
})

test_that("a brief call returns the rows as csv text", {
  local_fake_server()
  raw <- ms_call_tool(
    "wds_get_data_from_vectors",
    vector_ids = I(2062815),
    latest_n = 12,
    detail = "brief",
    client = test_client()
  )

  # What the server's default answer holds for twelve rows, and what
  # ms_get_data() would be unable to read as rows.
  block <- raw$series[[1]]$observations
  expect_equal(block$format, "csv")
  expect_equal(block$rows, 12)
  expect_true(startsWith(block$csv, "ref_period,value\n2025-11-01,"))
  expect_null(raw$provenance$queried_at)
})

wds_long_columns <- c(
  "product_id", "coordinate", "vector_id", "context_citation",
  "context_table_id", "context_table_title", "context_table_url",
  "context_series_title", "context_unit", "context_scale",
  "context_frequency", "context_geography", "context_members",
  "context_table_release_time", "context_first_period",
  "context_last_period", "context_notes", "transformed", "ref_period",
  "value", "decimals", "scalar_factor_code", "scale_multiplier",
  "symbol_code", "status_code", "security_level_code", "release_time",
  "symbol", "status", "security_level"
)

test_that("a long StatCan result becomes one row per observation", {
  server <- local_fake_server()

  # Twelve observations: the server's brief result would hold them as CSV text.
  data <- ms_get_data(
    "wds_get_data_from_vectors",
    vector_ids = I(2062815),
    latest_n = 12,
    client = test_client()
  )

  call <- server$bodies()[[3]]$params$arguments
  expect_equal(call$detail, "full")
  expect_equal(call$arguments$latest_n, 12)
  expect_equal(dim(data), c(12L, 30L))
  expect_named(data, wds_long_columns)
  expect_equal(data$ref_period[c(1, 12)], c("2025-11-01", "2026-10-01"))
  expect_type(data$value, "double")
  expect_false(anyNA(data$value))
  expect_equal(unique(data$vector_id), 2062815)
  expect_equal(unique(data$context_unit), "Percent")
  expect_equal(attr(data, "citation"), data$context_citation[[1]])
  expect_match(attr(data, "citation"), "Table 14-10-0287-01", fixed = TRUE)

  # A full result keeps the whole provenance, caveats and query time included.
  expect_equal(attr(data, "provenance")$source, "statcan-wds")
  expect_false(is.null(attr(data, "provenance")$queried_at))
  expect_length(attr(data, "provenance")$caveats, 2)
  expect_equal(attr(data, "left_out"), list(failed = "[list]"))
})

test_that("a long Bank of Canada result becomes one row per date", {
  server <- local_fake_server()
  data <- ms_get_data(
    "boc_get_observations",
    series_names = I("FXUSDCAD"),
    recent = 12,
    client = test_client()
  )

  expect_equal(server$bodies()[[3]]$params$arguments$detail, "full")
  expect_equal(dim(data), c(12L, 3L))
  expect_named(data, c("ref_date", "values_fxusdcad", "non_numeric"))
  expect_equal(length(unique(data$ref_date)), 12)
  expect_type(data$values_fxusdcad, "double")
  expect_false(anyNA(data$values_fxusdcad))
  expect_equal(attr(data, "provenance")$source, "boc")
  expect_match(attr(data, "provenance")$caveats[[1]], "^Indicative rate")
  expect_match(
    attr(data, "citation"),
    "^Source: boc\\. https://www\\.bankofcanada\\.ca/"
  )
  expect_equal(
    attr(data, "left_out"),
    list(series = "[object]", transformed = NA)
  )
})

scale_note <- paste(
  "Values are in thousands: multiply value by scale_multiplier",
  "for the full figure."
)
latest_note <- "The latest period is preliminary and may be revised."

test_that("notes the server states once are written back into the rows", {
  local_fake_server()
  client <- test_client()

  # wds_two was shaped by the server's own shape(): the note both series
  # share is in a top-level `shared_notes` list and each series holds a
  # reference.
  raw <- ms_call_tool(
    "wds_get_data_from_vectors",
    vector_ids = I(c(2062810, 2062811)),
    latest_n = 3,
    client = client
  )
  expect_equal(raw$shared_notes, list(scale_note))
  expect_equal(raw$series[[1]]$context$notes[[1]], "shared_notes[0]")

  data <- ms_get_data(
    "wds_get_data_from_vectors",
    vector_ids = I(c(2062810, 2062811)),
    latest_n = 3,
    client = client
  )
  expect_equal(nrow(data), 6)
  expect_equal(data$vector_id, rep(c(2062810, 2062811), each = 3))
  expect_equal(
    data$context_notes,
    rep(c(paste0(scale_note, "; ", latest_note), scale_note), each = 3)
  )
  expect_false(any(grepl("shared_notes", unlist(data), fixed = TRUE)))
  expect_equal(attr(data, "left_out"), list(failed = "[list]"))
  expect_equal(
    attr(data, "citation"),
    c(data$context_citation[[1]], data$context_citation[[4]])
  )
})

test_that("references are resolved wherever they stand", {
  # A wrapped list result: shared_notes sits beside "result" (shape() output).
  shared <- "A note long enough to be shared across items of the list."
  wrapped <- list(
    result = list(
      list(name = "alpha", notes = list("shared_notes[0]", "Kept.")),
      list(
        name = "beta",
        notes = list("shared_notes[0]"),
        note = "shared_notes[9]"
      )
    ),
    shared_notes = list(shared)
  )

  resolved <- resolve_shared_notes(wrapped)
  expect_equal(
    resolved,
    list(
      result = list(
        list(name = "alpha", notes = list(shared, "Kept.")),
        # An index past the list is left as it came.
        list(name = "beta", notes = list(shared), note = "shared_notes[9]")
      )
    )
  )
  tidy <- rows_and_left_out(resolved)
  expect_equal(tidy$rows[[2]]$notes, shared)
  expect_equal(tidy$left_out, list())

  # Without shared_notes the payload is returned as it is.
  plain <- list(series = list(list(notes = list("shared_notes[0]"))))
  expect_identical(resolve_shared_notes(plain), plain)
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
