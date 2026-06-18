function deep_nesting(items) {
  for (const a of items) {
    if (a) {
      while (a) {
        try {
          if (a) {
            return a;
          }
        } finally {
        }
      }
    }
  }
  return null;
}
