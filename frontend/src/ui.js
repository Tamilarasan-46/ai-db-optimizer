// Tiny global UI store: Vue-native toasts + confirm dialog.
// Replaces every browser-native alert()/confirm() in the app.
import { reactive } from 'vue'

export const ui = reactive({
  toasts: [],     // { id, message, type: 'success'|'error'|'warning'|'info' }
  confirm: null,  // { title, message, code, confirmText, resolve }
})

let nextId = 0

export function notify(message, type = 'info', timeout = 5000) {
  const id = ++nextId
  ui.toasts.push({ id, message, type })
  if (timeout) setTimeout(() => dismiss(id), timeout)
  return id
}

export function dismiss(id) {
  const i = ui.toasts.findIndex(t => t.id === id)
  if (i > -1) ui.toasts.splice(i, 1)
}

/** Vue-native confirm. Usage: if (await confirmDialog({...})) { ... } */
export function confirmDialog({ title, message, code = '', confirmText = 'Confirm', danger = false }) {
  return new Promise(resolve => {
    ui.confirm = { title, message, code, confirmText, danger, resolve }
  })
}

export function settleConfirm(value) {
  ui.confirm?.resolve(value)
  ui.confirm = null
}
