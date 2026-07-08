# case con 4 `when` explicitos y sin else: cada when suma +1 (else seria el camino
# base y NO sumaria, modelo 'ramas - 1' analogo a Go/PHP/Python/Rust).
def switch_case(x)
  case x
  when 0
    0
  when 1
    1
  when 2
    2
  when 3
    3
  end
end
