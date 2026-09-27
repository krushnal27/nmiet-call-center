class Queue:

    def __init__(self):
        self.items = []

    def enqueue(self, item):
        self.items.append(item)

    def dequeue(self):
        if self.is_empty():
            return None

        return self.items.pop(0)

    def display(self):
        return self.items.copy()

    def size(self):
        return len(self.items)

    def is_empty(self):
        return len(self.items) == 0

    def clear(self):
        self.items.clear()