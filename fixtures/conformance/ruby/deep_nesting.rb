# Anidamiento profundo (5 niveles: for>if>while>begin>if). begin/ensure es el
# try/finally de Ruby: anida SIN ser decision (analogo del `with` de Python).
def deep_nesting(items)
  for a in items
    if a
      while a
        begin
          if a
            return a
          end
        ensure
          nil
        end
      end
    end
  end
  0
end
