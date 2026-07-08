/* switch con 3 cases + default: la gramatica NO distingue `case` de `default` por
   tipo (ambos case_statement), asi que default suma +1 (modelo TS/Java). */
int switch_case(int x) {
    switch (x) {
    case 0:
        return 0;
    case 1:
        return 1;
    case 2:
        return 2;
    default:
        return 3;
    }
}
