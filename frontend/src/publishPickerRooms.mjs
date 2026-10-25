// Group metadata keeps room filters usable if the separate rooms request fails.
export function publishPickerRooms(rooms, groups) {
  const result = new Map()
  for (const room of rooms || []) {
    const id = Number(room.id)
    if (Number.isInteger(id) && id > 0 && room.name) result.set(id, { ...room, id })
  }
  for (const group of groups || []) {
    const id = Number(group.room_id)
    if (Number.isInteger(id) && id > 0 && group.room_name && !result.has(id)) {
      result.set(id, { id, name: group.room_name })
    }
  }
  return [...result.values()]
}
