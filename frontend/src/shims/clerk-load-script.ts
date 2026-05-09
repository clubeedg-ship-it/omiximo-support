import {
  buildClerkJsScriptAttributes,
  clerkJsScriptUrl,
  loadClerkJsScript,
  setClerkJsLoadingErrorPackageName,
} from '../../node_modules/@clerk/shared/dist/runtime/loadClerkJsScript.mjs'

const loadClerkUiScript = loadClerkJsScript

export {
  buildClerkJsScriptAttributes,
  clerkJsScriptUrl,
  loadClerkJsScript,
  loadClerkUiScript,
  setClerkJsLoadingErrorPackageName,
}
