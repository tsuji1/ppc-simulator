def calculate_capacity(tag_size,entry):
    # Calculate the capacity of the system
    data_size = 32
    all_size = tag_size + data_size
    capacity = all_size * entry
    return capacity/8

t = 18
e = 8
print(calculate_capacity(t,e))
    