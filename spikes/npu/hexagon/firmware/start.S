// Where the Hexagon core starts: give C a stack and call it. serve() never
// returns; the loop after it is for the day it does.
    .text
    .globl _start
_start:
    r29 = ##_stack_top
    call serve
1:
    jump 1b
