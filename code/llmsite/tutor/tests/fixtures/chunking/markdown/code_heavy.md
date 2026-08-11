# Introduction to Loops

A loop repeats a block of instructions. The `for` loop is the most common form
when you know in advance how many repetitions you need.

```python
total = 0
for i in range(1, 11):
    total = total + i
print(total)
```

That program adds the whole numbers from 1 to 10 and prints 55. The variable
`total` is called an accumulator because it accumulates the running sum.

A `while` loop repeats for as long as a condition stays true:

```python
count = 10
while count > 0:
    print(count)
    count = count - 1
print("Liftoff")
```

Be careful: if the condition never becomes false the loop runs forever. Always
make sure something inside the body changes the value the condition tests.
