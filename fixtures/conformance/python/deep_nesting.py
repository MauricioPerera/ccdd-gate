def deep_nesting(items):
    for a in items:
        if a:
            while a:
                with open(a) as h:
                    if h:
                        return a
    return None
