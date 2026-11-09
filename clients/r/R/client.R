# Talk to the MapleStats MCP endpoint over streamable HTTP, without an MCP SDK.
# Design: docs/clients.md in the maplestats-mcp repository.

default_url <- "https://mcp.maplestats.danielstats.io/mcp"
protocol_version <- "2025-06-18"
package_version <- "0.1.0"

# The server's own tools, called by name; every other tool goes through
# call_tool.
direct_tools <- c("search_tools", "plan_query", "call_tool")

the <- new.env(parent = emptyenv())

env_value <- function(name) {
  value <- Sys.getenv(name)
  if (nzchar(value)) value else NULL
}

#' Create a MapleStats client
#'
#' @param url Server address. Defaults to `MAPLESTATS_URL`, else the hosted
#'   server.
#' @param token Bearer token, only for a self-hosted server started with
#'   `MAPLE_AUTH_TOKEN`. Defaults to `MAPLESTATS_TOKEN`.
#' @param timeout Seconds to wait for a reply. The hosted server lets a tool
#'   call run 230 s.
#' @return A client object (an environment holding the session).
#' @export
ms_client <- function(url = NULL, token = NULL, timeout = 240) {
  client <- new.env(parent = emptyenv())
  client$url <- url %||% env_value("MAPLESTATS_URL") %||% default_url
  client$token <- token %||% env_value("MAPLESTATS_TOKEN")
  client$timeout <- timeout
  client$session <- NULL
  client$last_id <- 0L
  structure(client, class = "maplestats_client")
}

#' @export
print.maplestats_client <- function(x, ...) {
  status <- if (is.null(x$session)) "no session yet" else "session open"
  cat("<maplestats_client> ", x$url, " (", status, ")\n", sep = "")
  invisible(x)
}

#' The client the ms_ functions use by default
#'
#' Created on first use with [ms_client()] defaults.
#' @return A client object.
#' @export
ms_default_client <- function() {
  if (is.null(the$client)) {
    the$client <- ms_client()
  }
  the$client
}

maplestats_abort <- function(message, class = NULL, ...) {
  rlang::abort(message, class = c(class, "maplestats_error"), ...)
}

next_id <- function(client) {
  client$last_id <- client$last_id + 1L
  client$last_id
}

post_message <- function(client, body) {
  request <- httr2::request(client$url) |>
    httr2::req_headers(accept = "application/json, text/event-stream") |>
    httr2::req_user_agent(paste0("maplestats-r/", package_version)) |>
    httr2::req_body_json(body, auto_unbox = TRUE, null = "null") |>
    httr2::req_timeout(client$timeout) |>
    httr2::req_error(is_error = \(response) FALSE)

  # The session headers exist only after initialize.
  if (!is.null(client$session)) {
    request <- request |>
      httr2::req_headers(
        `mcp-session-id` = client$session,
        `mcp-protocol-version` = protocol_version
      )
  }
  if (!is.null(client$token)) {
    request <- request |> httr2::req_auth_bearer_token(client$token)
  }

  response <- httr2::req_perform(request)
  status <- httr2::resp_status(response)

  # The hosted server allows 60 requests a minute per client.
  if (status == 429) {
    retry <- httr2::resp_header(response, "retry-after")
    maplestats_abort(
      paste0(
        "Rate limited by ", client$url, "; retry after ",
        retry %||% "a minute", " s."
      ),
      class = "maplestats_rate_limited",
      retry_after = suppressWarnings(as.numeric(retry))
    )
  }
  response
}

check_status <- function(client, response) {
  status <- httr2::resp_status(response)
  if (status >= 400) {
    text <- if (httr2::resp_has_body(response)) {
      substr(httr2::resp_body_string(response), 1, 300)
    } else {
      ""
    }
    maplestats_abort(paste0("HTTP ", status, " from ", client$url, ": ", text))
  }
  invisible(response)
}

# The JSON-RPC response in a JSON or server-sent-events body.
parse_message <- function(response, request_id) {
  type <- httr2::resp_content_type(response)
  text <- httr2::resp_body_string(response)
  if (identical(type, "application/json")) {
    return(jsonlite::fromJSON(text, simplifyVector = FALSE))
  }

  # An event is its data: lines up to the next blank line.
  lines <- stringr::str_split_1(text, "\r?\n")
  event <- cumsum(lines == "")
  is_data <- stringr::str_starts(lines, "data:")
  data <- stringr::str_replace(lines[is_data], "^data: ?", "")
  messages <- split(data, event[is_data]) |>
    purrr::map(\(part) {
      jsonlite::fromJSON(paste(part, collapse = "\n"), simplifyVector = FALSE)
    })

  answer <- purrr::detect(messages, \(m) identical(m$id, request_id))
  if (is.null(answer)) {
    maplestats_abort(
      paste0("No response to request ", request_id, " in the server's reply.")
    )
  }
  answer
}

open_session <- function(client) {
  client$session <- NULL
  id <- next_id(client)
  response <- post_message(client, list(
    jsonrpc = "2.0",
    id = id,
    method = "initialize",
    params = list(
      protocolVersion = protocol_version,
      capabilities = structure(list(), names = character()),
      clientInfo = list(name = "maplestats-r", version = package_version)
    )
  ))
  check_status(client, response)
  message <- parse_message(response, id)
  if (!is.null(message$error)) {
    maplestats_abort(message$error$message %||% "initialize failed")
  }
  client$session <- httr2::resp_header(response, "mcp-session-id")

  initialized <- list(jsonrpc = "2.0", method = "notifications/initialized")
  check_status(client, post_message(client, initialized))
  invisible(client)
}

rpc_request <- function(client, method, params) {
  if (is.null(client$session)) {
    open_session(client)
  }
  body <- list(
    jsonrpc = "2.0", id = next_id(client), method = method,
    params = params
  )
  response <- post_message(client, body)

  # The server drops idle sessions after 5 minutes: open a new one, once.
  if (httr2::resp_status(response) == 404 && !is.null(client$session)) {
    open_session(client)
    body$id <- next_id(client)
    response <- post_message(client, body)
  }

  check_status(client, response)
  message <- parse_message(response, body$id)
  if (!is.null(message$error)) {
    maplestats_abort(message$error$message %||% paste(method, "failed"))
  }
  message$result
}

# A tools/call result's value: structuredContent, unwrapped, or its text.
decode_result <- function(result) {
  text <- paste(purrr::map_chr(
    result$content %||% list(),
    \(block) block$text %||% ""
  ), collapse = " ")
  if (isTRUE(result$isError)) {
    maplestats_abort(if (nzchar(text)) text else "The tool returned an error.")
  }

  structured <- result$structuredContent
  wrapped <- isTRUE(result$`_meta`$fastmcp$wrap_result)
  only_result <- is_object(structured) &&
    identical(names(structured), "result")
  if (wrapped && only_result) {
    return(structured$result)
  }
  if (!is.null(structured)) {
    return(structured)
  }
  tryCatch(
    jsonlite::fromJSON(text, simplifyVector = FALSE),
    error = \(e) text
  )
}

json_object <- function(x) {
  if (length(x) == 0) structure(list(), names = character()) else x
}

call_server_tool <- function(client, name, arguments) {
  arguments <- json_object(arguments)
  params <- if (name %in% direct_tools) {
    list(name = name, arguments = arguments)
  } else {
    list(
      name = "call_tool",
      arguments = list(name = name, arguments = arguments)
    )
  }
  decode_result(rpc_request(client, "tools/call", params))
}

#' Search the server's tools
#'
#' @param query What you need, in plain English or French, e.g.
#'   `"Calgary rent index"`.
#' @param client A client from [ms_client()].
#' @param detail `"full"` (the default) for each tool's whole description
#'   and input schema, or `"brief"` for a one-line description and the
#'   one-line argument signature.
#' @return A tibble with one row per tool, best match first: `name`,
#'   `description`, `arguments` (the one-line signature, `NA` with
#'   `detail = "full"`) and `input_schema` (JSON text, `NA` with
#'   `detail = "brief"`).
#' @export
ms_search_tools <- function(query,
                            client = ms_default_client(),
                            detail = "full") {
  found <- tryCatch(
    call_server_tool(
      client,
      "search_tools",
      list(query = query, detail = detail)
    ),
    maplestats_error = function(error) {
      # A server older than the compact search has no `detail` and rejects
      # it; its answer is the full form anyway.
      if (!grepl("detail", conditionMessage(error), fixed = TRUE)) {
        stop(error)
      }
      call_server_tool(client, "search_tools", list(query = query))
    }
  )
  tools <- if (is_record_list(found)) found else list()

  tibble::tibble(
    name = purrr::map_chr(tools, \(t) t$name %||% ""),
    description = purrr::map_chr(tools, \(t) t$description %||% ""),
    arguments = purrr::map_chr(tools, \(t) t$arguments %||% NA_character_),
    input_schema = purrr::map_chr(tools, \(t) {
      if (is.null(t$inputSchema)) {
        return(NA_character_)
      }
      as.character(jsonlite::toJSON(t$inputSchema, auto_unbox = TRUE))
    })
  )
}

#' Plan a question that may need several sources
#'
#' @param question The question, in English or French.
#' @param lang `"en"` or `"fr"`.
#' @param client A client from [ms_client()].
#' @return The plan as a list: topics, the tools to call in order, caveats.
#' @export
ms_plan_query <- function(question, lang = "en", client = ms_default_client()) {
  call_server_tool(client, "plan_query", list(question = question, lang = lang))
}

#' Call a tool and return its raw result
#'
#' Arguments are sent as JSON. A vector of length one becomes a JSON scalar;
#' wrap it in `I()` when the tool expects an array, e.g.
#' `series_names = I("FXUSDCAD")`.
#'
#' @param tool Tool name, as [ms_search_tools()] returns it.
#' @param ... The tool's arguments, by name.
#' @param client A client from [ms_client()].
#' @return The result as a list, provenance included.
#' @export
ms_call_tool <- function(tool, ..., client = ms_default_client()) {
  call_server_tool(client, tool, list(...))
}

#' Call a tool and return its rows as a tibble
#'
#' The rows are the result's largest list of objects; a series' observations
#' become one row each, carrying the series' fields. Nested fields become
#' `parent_child` columns and names are cleaned to snake_case. Values keep
#' their JSON types: dates stay text.
#'
#' @inheritParams ms_call_tool
#' @return A tibble with attributes `citation` (character), `provenance`,
#'   `left_out` (fields of the result beside the rows), `tool` and
#'   `arguments`.
#' @export
ms_get_data <- function(tool, ..., client = ms_default_client()) {
  arguments <- list(...)
  raw <- call_server_tool(client, tool, arguments)
  tidy <- rows_and_left_out(raw)

  data <- rows_to_tibble(tidy$rows)
  attr(data, "citation") <- result_citation(raw)
  attr(data, "provenance") <- result_provenance(raw)
  attr(data, "left_out") <- tidy$left_out
  attr(data, "tool") <- tool
  attr(data, "arguments") <- arguments
  data
}

#' Get a script that fetches the same data straight from the publisher
#'
#' @param tool Tool name.
#' @param arguments The tool's arguments, as a named list.
#' @param language `"r"`, `"python"`, `"stata"`, `"julia"`, `"excel"` or
#'   `"all"`.
#' @param lang `"en"` or `"fr"` for the notes.
#' @param client A client from [ms_client()].
#' @return The server's result: `scripts` (language, code, packages),
#'   `source_url`, `method` and `notes`.
#' @export
ms_reproduce_code <- function(tool, arguments, language = "r", lang = "en",
                              client = ms_default_client()) {
  call_server_tool(client, "reproduce_code", list(
    tool_name = tool,
    arguments = json_object(arguments),
    language = language,
    lang = lang
  ))
}
