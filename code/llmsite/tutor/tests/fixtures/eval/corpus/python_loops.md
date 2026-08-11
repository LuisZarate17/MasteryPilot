# Loops in Python

A loop repeats a block of instructions. The `for` loop is the most common form
when you know in advance how many repetitions you need.

```python
total = 0
for i in range(1, 11):
    total = total + i
print(total)
```

That program adds the whole numbers from 1 to 10 and prints 55. The variable
`total` is called an accumulator, because it accumulates the running sum as the
loop proceeds.

## While loops

A `while` loop repeats for as long as its condition stays true. Use it when you
do not know the number of repetitions ahead of time.

```python
count = 10
while count > 0:
    print(count)
    count = count - 1
print("Liftoff")
```

If the condition never becomes false the loop runs forever. Make sure something
inside the body changes the value the condition tests.
