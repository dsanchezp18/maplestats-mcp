# Turn a tool result into rows, the way the server's reproduce_workbook does.
# A port of rows_and_left_out() in
# src/maplestats_mcp/modules/reproduce/workbook.py; keep the two in step.
# JSON objects arrive as named lists and arrays as unnamed lists
# (jsonlite::fromJSON(simplifyVector = FALSE)).

is_object <- function(x) {
  is.list(x) && !is.null(names(x))
}

is_record_list <- function(x) {
  is.list(x) && is.null(names(x)) && length(x) > 0 &&
    all(purrr::map_lgl(x, is_object))
}

without_provenance <- function(x) {
  x[names(x) != "provenance"]
}

# The values one level down from every object in the frontier.
next_frontier <- function(frontier) {
  frontier |>
    purrr::keep(is_object) |>
    purrr::map(\(node) unname(without_provenance(node))) |>
    purrr::list_flatten()
}

# Every list of objects in the payload, three levels deep, provenance aside.
record_lists <- function(payload) {
  levels <- purrr::accumulate(
    1:3,
    \(frontier, level) next_frontier(frontier),
    .init = list(payload)
  )

  levels |>
    purrr::list_flatten() |>
    purrr::keep(is_record_list)
}

scalar_text <- function(value) {
  if (is.null(value)) "" else as.character(value)
}

# Nested objects become dotted names; lists become text.
flatten_record <- function(record, prefix = "") {
  record <- without_provenance(record)

  record |>
    purrr::imap(\(value, key) {
      name <- paste0(prefix, key)

      # Each JSON type takes a different path; this is not row-level recoding.
      if (is_object(value)) {
        return(flatten_record(value, paste0(name, ".")))
      }
      if (is.list(value)) {
        scalar <- !any(purrr::map_lgl(value, is.list))
        text <- if (scalar) {
          paste(purrr::map_chr(value, scalar_text), collapse = "; ")
        } else {
          jsonlite::toJSON(value, auto_unbox = TRUE, null = "null") |>
            as.character()
        }
        return(rlang::set_names(list(text), name))
      }
      rlang::set_names(list(value %||% NA), name)
    }) |>
    unname() |>
    purrr::list_flatten()
}

holds <- function(node, best) {
  if (identical(node, best)) {
    return(TRUE)
  }
  is_object(node) &&
    any(purrr::map_lgl(without_provenance(node), \(v) holds(v, best)))
}

# The result's fields outside the rows, by dotted name.
left_out <- function(node, best, prefix = "") {
  if (!is_object(node)) {
    return(list())
  }

  node |>
    without_provenance() |>
    purrr::discard(\(value) identical(value, best)) |>
    purrr::imap(\(value, key) {
      name <- paste0(prefix, key)

      # Same JSON-type dispatch as flatten_record().
      if (is_object(value) && holds(value, best)) {
        return(left_out(value, best, paste0(name, ".")))
      }
      marker <- if (is_object(value)) {
        "[object]"
      } else if (is.list(value)) {
        "[list]"
      } else {
        value %||% NA
      }
      rlang::set_names(list(marker), name)
    }) |>
    unname() |>
    purrr::list_flatten()
}

unwrap_result <- function(payload) {
  wrapped <- is_object(payload) && is.list(payload$result) &&
    is.null(names(payload$result))
  if (wrapped) {
    return(payload$result)
  }
  payload
}

# The table a result holds (its largest list of objects) and what it leaves
# out. When each object holds its own list of objects (a series and its
# observations), every inner object is one row carrying the outer fields.
rows_and_left_out <- function(payload) {
  payload <- unwrap_result(payload)
  lists <- record_lists(payload)

  # A result with no list of objects is one row, or none.
  if (length(lists) == 0) {
    single <- if (is_object(payload)) without_provenance(payload) else list()
    rows <- if (length(single) > 0) list(flatten_record(single)) else list()
    return(list(rows = rows, left_out = list()))
  }

  best <- lists[[which.max(purrr::map_int(lists, length))]]
  left <- left_out(payload, best)
  first <- best[[1]]
  child_keys <- names(first)[purrr::map_lgl(first, is_record_list)]

  # Rows without inner lists of objects are flattened as they are.
  if (length(child_keys) == 0) {
    return(list(rows = purrr::map(best, flatten_record), left_out = left))
  }

  child_sizes <- purrr::map_int(
    child_keys,
    \(key) sum(purrr::map_int(best, \(row) length(row[[key]])))
  )
  key <- child_keys[[which.max(child_sizes)]]

  rows <- best |>
    purrr::map(\(parent) {
      outer <- flatten_record(parent[names(parent) != key])
      purrr::map(
        parent[[key]],
        \(child) utils::modifyList(outer, flatten_record(child))
      )
    }) |>
    purrr::list_flatten()

  list(rows = rows, left_out = left)
}

# snake_case, ASCII only, as janitor::clean_names() does.
clean_name <- function(name) {
  plain <- iconv(name, from = "UTF-8", to = "ASCII//TRANSLIT", sub = "")

  cleaned <- plain |>
    stringr::str_replace_all("([a-z0-9])([A-Z])", "\\1_\\2") |>
    stringr::str_to_lower() |>
    stringr::str_replace_all("[^0-9a-z]+", "_") |>
    stringr::str_replace_all("^_+|_+$", "")

  replace(cleaned, is.na(cleaned) | cleaned == "", "x")
}

# clean_name() for each, with names that clean alike numbered from 2
# (a, a_2, a_3), as janitor does.
clean_names <- function(names) {
  cleaned <- clean_name(names)
  repeat_number <- stats::ave(seq_along(cleaned), cleaned, FUN = seq_along)
  repeated <- repeat_number > 1
  cleaned[repeated] <- paste0(cleaned[repeated], "_", repeat_number[repeated])
  cleaned
}

# A list of flat records as a tibble, one column per name in first-seen order.
rows_to_tibble <- function(rows) {
  columns <- unique(unlist(purrr::map(rows, names)))
  if (length(columns) == 0) {
    return(tibble::tibble())
  }

  values <- columns |>
    purrr::map(\(column) {
      purrr::map(rows, \(row) row[[column]] %||% NA) |>
        purrr::list_simplify(strict = FALSE)
    }) |>
    rlang::set_names(clean_names(columns))

  tibble::as_tibble(values)
}

# The result's provenance, or its first item's for a list result.
result_provenance <- function(payload) {
  payload <- unwrap_result(payload)
  if (is_record_list(payload)) {
    payload <- payload[[1]]
  }
  found <- if (is_object(payload)) payload$provenance else NULL
  if (is_object(found)) found else list()
}

# Every `citation` string anywhere in the result.
find_citations <- function(node) {
  if (!is.list(node)) {
    return(character())
  }
  own <- if (is_object(node) && is.character(node$citation)) {
    node$citation
  } else {
    character()
  }
  c(own, unlist(purrr::map(unname(node), find_citations)))
}

# Each distinct citation in the result, else one built from provenance.
result_citation <- function(payload) {
  found <- unique(find_citations(payload))
  if (length(found) > 0) {
    return(found)
  }

  source <- result_provenance(payload)
  if (length(source) == 0) {
    return(character())
  }
  parts <- c(
    paste0("Source: ", source$source %||% "unknown", "."),
    source$url,
    if (!is.null(source$queried_at)) paste0("(queried ", source$queried_at, ")")
  )
  paste(parts, collapse = " ")
}
