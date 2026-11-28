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

# The recording that answers a tools/call, as the real server would choose it.
# A call_tool without detail = "full" gets the server's brief result, where a
# list of six or more rows is CSV text; the long recordings have a _brief twin
# for that. Every other recording is the same whatever `detail` says.
answer_for <- function(params) {
  name <- fixture_for(params)
  asked_full <- params$name != "call_tool" ||
    identical(params$arguments$detail, "full")
  brief <- paste0(name, "_brief")
  if (!asked_full && file.exists(fixture_path(paste0(brief, ".sse")))) {
    return(brief)
  }
  name
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
    sse_response(recorded_body(answer_for(body$params), body$id))
  }
  state$bodies <- function() lapply(state$seen, sent_body)
  state
}

local_fake_server <- function(env = parent.frame()) {
  server <- fake_server()
  httr2::local_mocked_responses(server$mock, env = env)
  server
}

# A tool error as the server sends it: an isError result in one event.
error_response <- function(request_id, text) {
  error <- list(
    jsonrpc = "2.0",
    id = request_id,
    result = list(
      content = list(list(type = "text", text = text)),
      isError = TRUE
    )
  )
  sse_response(paste0(
    "data: ",
    jsonlite::toJSON(error, auto_unbox = TRUE),
    "\n\n"
  ))
}

# What a server that does not know `detail` says, word for word: the project's
# own validation message, as the v0.5.0 server gave it (a call_tool error names
# the inner tool and lists that tool's parameters), in English and in French.
old_server_errors <- c(
  "detail is not a parameter of this tool; parameters: query",
  paste(
    "[invalid_input] Invalid input: boc_get_observations: detail is not a",
    "parameter of this tool; parameters: aggregation, lang, recent,",
    "series_names Fix: correct the argument named above."
  ),
  "detail n'est pas un paramètre de cet outil; paramètres : query",
  paste0(
    "[invalid_input] Entrée invalide\u00a0: boc_get_observations\u00a0: ",
    "detail n'est pas un paramètre de cet outil; paramètres\u00a0: lang, ",
    "recent, series_names Solution\u00a0: corrigez l'argument nommé ci-dessus."
  )
)

# Errors that mention `detail` or an unknown argument without being that
# refusal: a current server's invalid-arguments error quotes a tool's
# parameters (one is called "details"), and the earlier loose wording
# ("Unexpected argument: detail").
not_the_refusal <- c(
  paste(
    "Invalid input: some_tool: kind is not a parameter of this tool;",
    "parameters: details, lang"
  ),
  "Invalid input: some_tool: detail must be one of 'brief' or 'full' (got 'x')",
  "Unexpected argument: detail",
  "Unknown series: detail",
  "No detail found for FXUSDCAD."
)

search_columns <- c("name", "description", "arguments", "input_schema")

test_client <- function() {
  ms_client(url = "https://test.invalid/mcp")
}
