# A fake MapleStats server that answers from the recorded responses in
# fixtures/ (written by clients/record_fixtures.py).

fixture_path <- function(name) {
  test_path("fixtures", name)
}

recorded_requests <- jsonlite::fromJSON(
  fixture_path("requests.json"),
  simplifyVector = FALSE
)

# The request body as the server would read it.
sent_body <- function(request) {
  json <- jsonlite::toJSON(request$body$data, auto_unbox = TRUE, null = "null")
  jsonlite::fromJSON(json, simplifyVector = FALSE)
}

sort_names <- function(x) {
  if (length(x) == 0) list() else x[order(names(x))]
}

# A recorded SSE body, its JSON-RPC id changed to the one the client sent.
recorded_body <- function(name, request_id) {
  lines <- readLines(fixture_path(paste0(name, ".sse")), encoding = "UTF-8")
  is_data <- startsWith(lines, "data:")
  lines[is_data] <- vapply(lines[is_data], function(line) {
    message <- jsonlite::fromJSON(substring(line, 6), simplifyVector = FALSE)
    message$id <- request_id
    paste0("data: ", jsonlite::toJSON(message,
      auto_unbox = TRUE,
      null = "null", digits = NA
    ))
  }, character(1))
  paste0(paste(lines, collapse = "\n"), "\n\n")
}

# Which recording answers a tools/call, matched on tool name and arguments.
fixture_for <- function(params) {
  tool <- params$name
  arguments <- params$arguments
  if (tool == "call_tool") {
    tool <- arguments$name
    arguments <- arguments$arguments
  }

  # lang = "en" is the server's default; the recordings leave it out.
  if (identical(arguments$lang, "en")) {
    arguments$lang <- NULL
  }
  for (name in names(recorded_requests)) {
    request <- recorded_requests[[name]]
    same_arguments <- identical(
      sort_names(request$arguments),
      sort_names(arguments)
    )
    if (identical(request$tool, tool) && same_arguments) {
      return(name)
    }
  }
  stop("No recording for ", tool, " ", jsonlite::toJSON(arguments))
}

sse_response <- function(text, headers = list()) {
  httr2::response(
    status_code = 200,
    headers = c(list(`content-type` = "text/event-stream"), headers),
    body = charToRaw(enc2utf8(text))
  )
}

# Returns the mock function and the requests it saw; `override` may answer a
# request instead (return NULL to fall through to the recordings).
fake_server <- function() {
  state <- new.env()
  state$seen <- list()
  state$override <- NULL
  state$mock <- function(req) {
    request <- req
    state$seen <- c(state$seen, list(request))
    if (!is.null(state$override)) {
      answer <- state$override(request)
      if (!is.null(answer)) {
        return(answer)
      }
    }
    body <- sent_body(request)
    if (body$method == "initialize") {
      return(sse_response(
        recorded_body("initialize", body$id),
        list(`mcp-session-id` = "test-session")
      ))
    }
    if (body$method == "notifications/initialized") {
      return(httr2::response(status_code = 202))
    }
    stopifnot(identical(request$headers$`mcp-session-id`, "test-session"))
    sse_response(recorded_body(fixture_for(body$params), body$id))
  }
  state$bodies <- function() lapply(state$seen, sent_body)
  state
}

local_fake_server <- function(env = parent.frame()) {
  server <- fake_server()
  httr2::local_mocked_responses(server$mock, env = env)
  server
}

search_columns <- c("name", "description", "arguments", "input_schema")

test_client <- function() {
  ms_client(url = "https://test.invalid/mcp")
}
