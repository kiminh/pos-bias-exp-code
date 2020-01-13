#!/bin/bash

source init.sh

l=16
r=-2
w=0.25

t=16

./train -k 8 -l $l -t $t -r $r -w $w -wn 1  -c 5 -o filter.model item.ffm rd.trva.ffm.cvt & 

echo "./train -k 8 -l $l -t $t -r $r -w $w -wn 1  -c 5 -o filter.model item.ffm rd.trva.ffm.cvt" > filter.model.param
