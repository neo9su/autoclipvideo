export const VERSION_ENDPOINTS = Object.freeze({
  classic: (groupId) => `/api/groups/${groupId}/merge`,
  director: (groupId) => `/api/groups/${groupId}/retry-director`,
  realistic: (groupId) => `/api/groups/${groupId}/retry-styles`,
  conservative: (groupId) => `/api/groups/${groupId}/retry-styles`,
  qianchuan: (groupId) => `/api/groups/${groupId}/retry-qianchuan`,
})

export const STYLE_VERSIONS = Object.freeze(['realistic', 'conservative'])
