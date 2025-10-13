import requests
import datetime
from HallucinationTest.stack import Stack  
from HallucinationTest.tag import Tag  
import re
class check:
    def __init__(self,texts):
        self.ErrorList=[]
        self.ActivityList=[]
        self.line0=[]  
        self.line_tag=[]   
        self.ToTag(texts)
        self.CheckPair(self.line_tag)
        self.CheckStructure(self.line_tag)

    def getError(self):
        # error_prompt = ' \n'.join(self.ErrorList)
        if len(self.ErrorList)!=0:
            error_prompt=self.ErrorList[0]
        else:
            error_prompt=''
        return error_prompt

    def remove_empty_lines(self,text):  
            lines = text.split('\n')
            non_empty_lines = [line for line in lines if line.strip()]
            return non_empty_lines

    def trim_string(self,s):  
        start = 0
        end = len(s)
        for i, char in enumerate(s):
            if not char.isspace():
                start = i
                break
        for i in range(len(s) - 1, -1, -1):
            if not s[i].isspace():
                end = i + 1
                break
        return s[start:end]

        
    def extract_tag_left(self,line): 
        tag_index = line.find("<")
        space_index = line.find(" ", tag_index)
        word = line[tag_index + 1:space_index]
        
        english_word=''.join(word)
        if english_word.isalpha():
            return english_word
        else:
            return ""
        
    def extract_tag_right(self,line): 
 
        tag_index = line.find("<")
        space_index = line.find(" ", tag_index)
        word = line[tag_index + 1:space_index]
        english_word = ''.join(filter(str.isalpha, word))
        if english_word.isalpha():
            return english_word
        else:
            return ""
        
    def extract_id(self,string): 
        match = re.search(r"id='([^']+)'", string)
        
        if match:
            return match.group(1)
        else:
            return ""
        
    def extract_condition(self,string):
        match = re.search(r"condition='([^']+)'", string)

        if match:
            return match.group(1)
        else:
            return ""

    def ToTag(self,texts):
        non_empty_lines=self.remove_empty_lines(texts)
        for index,line in enumerate(non_empty_lines):
            spaces=len(line) - len(line.lstrip())
            line2=self.trim_string(line) 
            self.line0.append(line2)
            if line=='<process>' or line=='</process>':
                continue

            if self.extract_tag_left(line2)=="activity":  
                parentheses=''  
                content='activity'  
                condition=''   
                idnum=self.extract_id(line2)  
            elif line2[0]=='<' and line2[1]!='/':  
                parentheses='<'  
                condition=self.extract_condition(line2) 
                tag_left=self.extract_tag_left(line2)
                if tag_left=='branch':  
                    content='branch'
                elif tag_left=='exclusiveGateway':
                    content='exclusiveGateway'
                elif tag_left=='parallelGateway':
                    content='parallelGateway'
                elif tag_left=='inclusiveGateway':
                    content='inclusiveGateway'
                else:
                    content='error'
                idnum=self.extract_id(line2) 

            elif line2[0]=='<' and line2[1]=='/': 
                parentheses='>'  
                tag_right=self.extract_tag_right(line2)
                if tag_right=='branch':  
                    content='branch'
                elif tag_right=='exclusiveGateway':
                    content='exclusiveGateway'
                elif tag_right=='parallelGateway':
                    content='parallelGateway'
                elif tag_right=='inclusiveGateway':
                    content='inclusiveGateway'
                else:
                    content='error'
                condition='' 
                idnum=self.extract_id(line2)  #id
            else:
                content='error'
                parentheses=''
                condition=''
                idnum=self.extract_id(line2)  #id
            row=index+1
            self.line_tag.append(Tag(spaces,parentheses,content,condition,row,idnum))

    def CheckPair(self,line_tag):
        stack1=Stack()
        index=0
        while index<len(line_tag):
            line=line_tag[index]
            if line.parentheses=="<" and line.content!="error":
                stack1.push(line)  
                index=index+1
            elif line.parentheses==">" and line.content!="error": 
                if stack1.isEmpty(): 
                    # print("error1")
                    self.ErrorList.append("The '</"+line.content+">' in line "+str(line.row)+" is not matched, please consider adding the matched tag in the appropriate position or removing the '</"+line.content+">' in line "+str(line.row)+".")  
                    index=index+1
                elif line.content==stack1.getTop().content and line.spaces==stack1.getTop().spaces:              
                    stack1.pop()
                    index=index+1
                else: 
                    if line.spaces<stack1.getTop().spaces:
                        # print("error2")
                        if len(stack1.getTop().condition)!=0: 
                            self.ErrorList.append("The '"+stack1.getTop().content+"' tag with id='"+stack1.getTop().idnum+"' is not matched, please consider adding the </"+stack1.getTop().content+"> in the appropriate position or removing the '"+stack1.getTop().content+"' tag with id='"+stack1.getTop().idnum+"'") 
                        else: 
                            self.ErrorList.append("The '"+stack1.getTop().content+"' tag with id='"+stack1.getTop().idnum+"' is not matched, please consider adding the </"+stack1.getTop().content+"> in the appropriate position or removing the '"+stack1.getTop().content+"' tag with id='"+stack1.getTop().idnum+"'") 
                        stack1.pop() 
                    else:  
                        self.ErrorList.append("The </"+line.content+"> in line "+str(line.row)+" is not matched, please consider adding the matched tag in the appropriate position or removing the </"+line.content+"> in line "+str(line.row)+".")  
                        index=index+1
                        continue  

            elif line.content=='activity':  
                index=index+1
                continue
            else:
                self.ErrorList.append("'"+self.line0[line.row-1]+"' on line "+str(line.row)+" does not conform to the format.")  
          
                index=index+1
        if not stack1.isEmpty():
            for line in stack1.items:
                self.ErrorList.append("The '"+stack1.getTop().content+"' tag with id="+stack1.getTop().idnum+"' is not matched, please consider adding the matched tag in the appropriate position or removing the '"+stack1.getTop().content+"' tag with id='"+stack1.getTop().idnum+"'.") 
             
    def CheckStructure(self,line_tag):
        stack2=Stack()
        index=0
        while index<len(line_tag):
            line=line_tag[index]
            if line.parentheses=="<" and line.content!="error": 
                stack2.push(line) 
            if line.parentheses==">" and line.content!="error":  
                if not stack2.isEmpty():
                    if line.content==stack2.getTop().content and line.spaces==stack2.getTop().spaces:  
                        if line.content=="branch":  
                            branch1=stack2.getTop()  
                            if line.row==stack2.getTop().row+1:  
                                self.ErrorList.append("There is a missing activity or branch between branch or gateway with id='"+stack2.getTop().idnum+"'. Consider adding activity or branch between them or removing the tag with id='"+stack2.getTop().idnum+"'.") 
                                stack2.pop()  
                            if int(len(stack2.items))!=0 and stack2.getTop().content=="branch" and stack2.getTop().spaces==branch1.spaces-2:
                                self.ErrorList.append("The branch tag with id='"+branch1.idnum+"' cannot be directly nested under the branch tag with id='"+stack2.getTop().idnum+"'. Consider removing the 'branch' tag with id='"+branch1.idnum+"' and its paired branch tag, or adding a gateway outside the branch tag with id='"+branch1.idnum+"'.")  

                        elif line.row==stack2.getTop().row+1: 
                            self.ErrorList.append("There is no activity or branch between the gateway with id='"+stack2.getTop().idnum+"'. Consider adding activity or branch between them or removing the gateway tag with id='"+stack2.getTop().idnum+"'.")  
                            stack2.pop() 
                        elif line.content=="exclusiveGateway": 
                            i=stack2.getTop().row 
                            branchnum=0
                            conditionnum=0
                            while i!=line.row:
                                if line_tag[i-1].parentheses=="<" and line_tag[i-1].content=='branch' and line_tag[i-1].spaces==line.spaces+2: 
                                    branchnum=branchnum+1  
                                    if len(line_tag[i-1].condition)!=0:
                                        conditionnum=conditionnum+1  
                                i=i+1

                            if branchnum<2:
                                self.ErrorList.append("The exclusive gateway with id='"+stack2.getTop().idnum+"' is missing branch (at least two branches). Consider adding branch between the exclusive gateway with id='"+stack2.getTop().idnum+"', or changing this exclusive gateway with id='"+stack2.getTop().idnum+"' to a sequential structure.") 
                                
                            if conditionnum!=0 and conditionnum!=branchnum:
                                self.ErrorList.append("In the exclusive gateway with id='"+stack2.getTop().idnum+"', some branches are conditional and some branches are not.It should be changed to either all conditions or none conditions.")  
                            stack2.pop()  
                        elif line.content=="parallelGateway":  
                            i=stack2.getTop().row 
                            branchnum=0
                            conditionnum=0
                            while i!=line.row:
                                if line_tag[i-1].parentheses=="<" and line_tag[i-1].content=='branch' and line_tag[i-1].spaces==line.spaces+2: 
                                    branchnum=branchnum+1  
                                    if len(line_tag[i-1].condition)!=0:
                                        conditionnum=conditionnum+1  
                                i=i+1
                            if branchnum<2:
                                self.ErrorList.append("The parallel gateway with id='"+stack2.getTop().idnum+"' is missing branch (at least two branches). Consider adding branch between the parallel gateway with id='"+stack2.getTop().idnum+"', or changing this parallel gateway with id='"+stack2.getTop().idnum+"' to a sequential structure.")  
                            if conditionnum!=0:
                                self.ErrorList.append("In the parallel gateway with id='"+stack2.getTop().idnum+"', all branches cannot be conditional. Consider either set the condition='' inside the parallel gateway with id='"+stack2.getTop().idnum+"' or changing the gateway to an exclusive gateway.")  
                            stack2.pop()  
                        elif line.content=="inclusiveGateway":  
                            i=stack2.getTop().row 
                            branchnum=0
                            conditionnum=0
                            while i!=line.row:
                                if line_tag[i-1].parentheses=="<" and line_tag[i-1].content=='branch' and line_tag[i-1].spaces==line.spaces+2: 
                                    branchnum=branchnum+1  
                                    if len(line_tag[i-1].condition)!=0:
                                        conditionnum=conditionnum+1  
                                i=i+1
                            if branchnum<2:
                                self.ErrorList.append("The inclusive gateway with id='"+stack2.getTop().idnum+"' is missing branch (at least two branches). Consider adding branch between the exclusive gateway with id='"+stack2.getTop().idnum+"', or changing this exclusive gateway with id='"+stack2.getTop().idnum+"' to a sequential structure.")  
                               
                            if conditionnum!=branchnum:
                                self.ErrorList.append("In the inclusive gateway with id='"+stack2.getTop().idnum+"', some branches do not have conditions. It should be add.")  
                                
                            stack2.pop()  
                    else:
                        if line.spaces<stack2.getTop().spaces:
                            stack2.pop()  
                            continue
                        else:
                            index=index+1
                            continue
            index=index+1



